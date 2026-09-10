from html import escape
import os
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# ==== Email Notification Config ====
# Values come from .env (see .env.example); the hardcoded fallbacks keep the
# existing Task Scheduler runs working even without a .env present.
SMTP_SERVER = os.environ.get('SMTP_SERVER', "smtp.gmail.com")
SMTP_PORT = int(os.environ.get('SMTP_PORT', 587))
SENDER_EMAIL = os.environ.get('NOTIFY_SENDER_EMAIL', 'samuel@vservesolution.com')
SENDER_APP_PASSWORD = os.environ.get('NOTIFY_SENDER_APP_PASSWORD', 'qyrg jkbx sasr aipo')
_recipients_env = os.environ.get(
    'NOTIFY_RECIPIENT_EMAILS',
    "samuel@vservesolution.com,ranganathan@vservesolution.com,nandhini@vservesolution.com,prabhu@vservesolution.com"
)
RECIPIENT_EMAILS = [r.strip() for r in _recipients_env.split(',') if r.strip()]
SHEET_URL = "https://docs.google.com/spreadsheets/d/1xdZtLvQZ6cshlI75-XuLU7dSuniL-2NIqVZ8mQYHUxk/edit"  # shown as the CTA button, optional


# The mobile tweaks live here (Gmail + Apple Mail support <style> media queries).
# Everything else is inline because Gmail's web client is unreliable with
# <style> rules, and it ignores flex/grid/gap — so all layout is table-based.
EMAIL_STYLES = """\
<style>
  @media only screen and (max-width: 800px) {
    .container { width: 100% !important; }
    .card-pad { padding-left: 16px !important; padding-right: 16px !important; }
    .header-pad { padding-left: 16px !important; padding-right: 16px !important; }
    .stat-td { padding: 14px 4px 12px !important; }
    .meta-row td { display: block !important; width: 100% !important; }
    .meta-link { text-align: left !important; padding-top: 10px !important; }
  }
</style>
"""


def build_html_email(replies_found, today_str, sheet_url=None):
    """Builds a modern, Gmail-friendly HTML email for LinkedIn reply detections.

    Compatibility notes (why it's built this way):
      - 600px max-width card — Gmail desktop scales down anything wider.
      - Tables for layout — Gmail/Outlook ignore flex, grid and gap.
      - Inline styles — Gmail web strips many <style> rules; only the mobile
        media query lives in <style>, which Gmail and Apple Mail do support.
      - Bulletproof CTA (VML + HTML fallback) so Outlook renders it too.
    """
    reply_count = len(replies_found)
    campaign_count = len({r.get("campaign") for r in replies_found if r.get("campaign")})
    account_count = len({r.get("account") for r in replies_found if r.get("account")})

    # Generate each reply card
    reply_cards = ""
    for r in replies_found:
        name = escape(r.get("name", "Unknown Lead"))
        message = escape(r.get("message", "") or "")
        sales_nav_url = escape(r.get("sales_nav_url", "#"), quote=True)
        campaigns = escape(r.get("campaign", "General Outreach"))
        account = escape(r.get("account", "Unknown Account"))
        snippet = (message[:200] + "…") if len(message) > 200 else message
        # Get initials for avatar
        initials = "".join(part[0] for part in name.split()[:2]).upper() or "L"

        reply_cards += f"""
        <div style="background:#ffffff;border:1px solid #e8ecf3;border-radius:14px;padding:16px 18px;margin:0 0 12px 0;">
          <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">
            <tr>
              <!-- Avatar -->
              <td width="48" style="vertical-align:top;padding-right:12px;">
                <div style="width:40px;height:40px;border-radius:50%;background:#4F46E5;background:linear-gradient(135deg,#4F46E5,#7C3AED);color:#ffffff;font-size:15px;font-weight:700;text-align:center;line-height:40px;font-family:Arial,Helvetica,sans-serif;">{initials}</div>
              </td>
              <!-- Name + Message + metadata -->
              <td style="vertical-align:top;">
                <div style="font-size:15px;font-weight:700;color:#0f172a;line-height:1.3;">{name}</div>
                <div style="margin-top:8px;background:#f8fafc;border:1px solid #eef1f6;border-left:3px solid #6366f1;border-radius:10px;padding:10px 14px;font-size:14px;color:#334155;line-height:1.55;word-break:break-word;overflow-wrap:break-word;">&ldquo;{snippet}&rdquo;</div>
                <!-- Campaign + Account badges + View message link (table, not flex) -->
                <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" class="meta-row" style="margin-top:10px;">
                  <tr>
                    <td class="meta-td" style="vertical-align:middle;">
                      <span style="display:inline-block;background:#eef2ff;color:#4338ca;font-size:12px;font-weight:600;padding:3px 10px;border-radius:30px;margin:0 4px 4px 0;">🎯 {campaigns}</span>
                      <span style="display:inline-block;background:#f1f5f9;color:#475569;font-size:12px;font-weight:600;padding:3px 10px;border-radius:30px;margin:0 4px 4px 0;">👤 {account}</span>
                    </td>
                    <td class="meta-link" align="right" style="vertical-align:middle;white-space:nowrap;">
                      <a href="{sales_nav_url}" target="_blank" style="color:#4F46E5;font-size:13px;font-weight:600;text-decoration:none;border-bottom:1px dashed #a5b4fc;">View message →</a>
                    </td>
                  </tr>
                </table>
              </td>
            </tr>
          </table>
        </div>
        """

    if not reply_cards:
        reply_cards = """
        <div style="background:#ffffff;border:1px solid #e8ecf3;border-radius:14px;padding:28px;text-align:center;">
          <div style="font-size:28px;">📭</div>
          <div style="font-size:15px;font-weight:700;color:#0f172a;margin-top:8px;">No new replies</div>
          <div style="font-size:13px;color:#64748b;margin-top:4px;">Nothing to report right now.</div>
        </div>
        """

    # Bulletproof CTA button: VML for Outlook, standard anchor everywhere else
    cta_button = ""
    if sheet_url:
        safe_sheet_url = escape(sheet_url, quote=True)
        cta_button = f"""
        <!--[if mso]>
          <v:roundrect xmlns:v="urn:schemas-microsoft-com:vml" xmlns:w="urn:schemas-microsoft-com:office:word" href="{safe_sheet_url}" style="height:46px;v-text-anchor:middle;width:210px;" arcsize="50%" stroke="f" fillcolor="#4F46E5">
            <w:anchorlock/>
            <center style="color:#ffffff;font-family:Arial,sans-serif;font-size:14px;font-weight:700;">Open Master Sheet</center>
          </v:roundrect>
        <![endif]-->
        <!--[if !mso]><!-->
          <a href="{safe_sheet_url}" target="_blank" style="display:inline-block;background:#4F46E5;color:#ffffff;padding:13px 30px;border-radius:50px;font-size:14px;font-weight:700;letter-spacing:0.3px;text-decoration:none;">📊 Open Master Sheet</a>
        <!--<![endif]-->
        """

    plural = "y" if reply_count == 1 else "ies"

    html = f"""<!DOCTYPE html>
<html lang="en" dir="ltr" xmlns="http://www.w3.org/1999/xhtml" xmlns:v="urn:schemas-microsoft-com:vml" xmlns:o="urn:schemas-microsoft-com:office:office">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <meta name="color-scheme" content="light">
  <meta name="supported-color-schemes" content="light">
  <title>Reply Report — {today_str}</title>
  {EMAIL_STYLES}
</head>
<body style="margin:0;padding:0;background-color:#f4f6fa;-webkit-text-size-adjust:100%;-ms-text-size-adjust:100%;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,'Helvetica Neue',Arial,sans-serif;">
  <!-- Hidden preheader (Gmail inbox preview text) -->
  <div style="display:none;max-height:0;overflow:hidden;mso-hide:all;font-size:1px;line-height:1px;color:#f4f6fa;opacity:0;">{reply_count} new LinkedIn repl{plural} from your outreach — see who responded and open the master sheet.</div>
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" bgcolor="#f4f6fa">
    <tr>
      <td align="center" style="padding:24px 12px;">
        <!-- Card container (600px max so Gmail desktop doesn't scale it down) -->
        <table role="presentation" class="container" align="center" width="800" cellpadding="0" cellspacing="0" border="0" style="width:800px;max-width:800px;">
          <tr>
            <td>
              <div style="background:#ffffff;border:1px solid #e8ecf3;border-radius:18px;overflow:hidden;">
                <!-- Header -->
                <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">
                  <tr>
                    <td class="header-pad" style="padding:32px 28px 28px;background:#312E81;background:linear-gradient(135deg,#1e1b4b 0%,#312E81 40%,#4F46E5 75%,#7C3AED 100%);text-align:center;">
                      <div style="font-size:18px;margin-bottom:8px;">📬</div>
                      <div style="color:#ffffff;font-size:24px;font-weight:800;letter-spacing:-0.3px;line-height:1.25;">{reply_count} new repl{plural}</div>
                      <div style="color:rgba(255,255,255,0.82);font-size:14px;margin-top:6px;">New responses from your LinkedIn outreach</div>
                      <div style="display:inline-block;margin-top:12px;background:rgba(255,255,255,0.16);border:1px solid rgba(255,255,255,0.25);padding:5px 16px;border-radius:30px;color:#ffffff;font-size:12px;font-weight:600;letter-spacing:0.4px;">{today_str}</div>
                    </td>
                  </tr>
                </table>

                <!-- Stats strip -->
                <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="background:#f8fafc;border-top:1px solid #eef1f6;border-bottom:1px solid #eef1f6;">
                  <tr>
                    <td class="stat-td" align="center" style="padding:18px 8px 16px;border-right:1px solid #e8ecf3;">
                      <div style="font-size:26px;font-weight:800;color:#0f172a;line-height:1;">{reply_count}</div>
                      <div style="font-size:11px;font-weight:700;color:#6366f1;text-transform:uppercase;letter-spacing:0.8px;margin-top:5px;">New Replies</div>
                    </td>
                    <td class="stat-td" align="center" style="padding:18px 8px 16px;border-right:1px solid #e8ecf3;">
                      <div style="font-size:26px;font-weight:800;color:#0f172a;line-height:1;">{campaign_count}</div>
                      <div style="font-size:11px;font-weight:700;color:#64748b;text-transform:uppercase;letter-spacing:0.8px;margin-top:5px;">Campaigns</div>
                    </td>
                    <td class="stat-td" align="center" style="padding:18px 8px 16px;">
                      <div style="font-size:26px;font-weight:800;color:#0f172a;line-height:1;">{account_count}</div>
                      <div style="font-size:11px;font-weight:700;color:#64748b;text-transform:uppercase;letter-spacing:0.8px;margin-top:5px;">Accounts</div>
                    </td>
                  </tr>
                </table>

                <!-- Replies section -->
                <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">
                  <tr>
                    <td class="card-pad" style="padding:24px 28px 4px;">
                      <div style="font-size:12px;font-weight:700;color:#64748b;text-transform:uppercase;letter-spacing:1px;">Replies</div>
                    </td>
                  </tr>
                  <tr>
                    <td class="card-pad" style="padding:14px 28px 24px;">
                      {reply_cards}
                    </td>
                  </tr>
                </table>

                <!-- CTA footer -->
                <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">
                  <tr>
                    <td class="card-pad" style="padding:26px 28px 30px;background:#f8fafc;border-top:1px solid #eef1f6;text-align:center;">
                      <div style="font-size:14px;color:#475569;font-weight:500;margin-bottom:16px;">All replies are logged in the master sheet.</div>
                      {cta_button}
                    </td>
                  </tr>
                </table>

                <!-- Fine print -->
                <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">
                  <tr>
                    <td class="card-pad" style="padding:16px 28px;text-align:center;">
                      <p style="color:#94a3b8;font-size:11px;margin:0;line-height:1.5;">Automated notification · LinkedIn Sales Navigator reply tracker · Vserve</p>
                    </td>
                  </tr>
                </table>
              </div>
              <!-- end card -->
            </td>
          </tr>
        </table>
        <!-- end container -->
      </td>
    </tr>
  </table>
</body>
</html>
"""
    return html


def send_reply_notification(replies_found, recipients=None, sheet_url=None):
    """
    Send a styled HTML email listing leads who replied.

    Args:
        replies_found: list of dicts with keys 'sales_nav_url', 'name', 'message', 'campaigns', 'account'
        recipients: optional list of email addresses to override RECIPIENT_EMAILS
        sheet_url: optional Google Sheet link shown as the CTA button (defaults to SHEET_URL)
    """
    if not replies_found:
        print("No replies to notify about — skipping email.")
        return

    if not SENDER_APP_PASSWORD:
        print("⚠️  NOTIFY_SENDER_APP_PASSWORD not set — skipping email notification.")
        return

    to_list = recipients or RECIPIENT_EMAILS
    today_str = datetime.now().strftime('%d %b %Y')
    subject = f"🔔 {len(replies_found)} new LinkedIn repl{'y' if len(replies_found) == 1 else 'ies'} — {today_str}"

    html_body = build_html_email(replies_found, today_str, sheet_url=sheet_url or SHEET_URL)

    msg = MIMEMultipart("alternative")
    msg['From'] = f'Linkedin Notification<{SENDER_EMAIL}>'
    msg['To'] = ", ".join(to_list)
    msg['Subject'] = subject

    # Plain-text fallback (includes the extra fields for completeness)
    plain_lines = []
    for r in replies_found:
        line = f"- {r.get('name', '')}: {(r.get('message') or '')[:150]}"
        if r.get('campaigns'):
            line += f" | Campaign: {r['campaigns']}"
        if r.get('account'):
            line += f" | Account: {r['account']}"
        if r.get('sales_nav_url'):
            line += f" | View: {r['sales_nav_url']}"
        plain_lines.append(line)
    plain_fallback = "\n".join(plain_lines)

    msg.attach(MIMEText(plain_fallback, 'plain'))
    msg.attach(MIMEText(html_body, 'html'))

    try:
        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
            server.starttls()
            server.login(SENDER_EMAIL, SENDER_APP_PASSWORD)
            server.sendmail(SENDER_EMAIL, to_list, msg.as_string())
        print(f"📧 Notification email sent to {', '.join(to_list)}")
    except Exception as e:
        print(f"❌ Failed to send email notification: {e}")


if __name__ == "__main__":
    # Quick manual test with all fields now included
    sample_replies = [
        {
            "sales_nav_url": "https://www.linkedin.com/sales/lead/ACwAAAJh3kIBAt_10s7ySrys_5R_9834yjCjcjY",
            "name": "Tim Tsouchlos",
            "message": "Thanks for reaching out, happy to chat next week about the supply chain platform.",
            "campaigns": "Supply Chain Q2",
            "account": "Acme Corp"
        },
        {
            "sales_nav_url": "https://www.linkedin.com/sales/lead/ACwAAAOqAC0BH9ZbPm-hxVWWFmoFYOF_pbCiafM",
            "name": "Troy Rector",
            "message": "Not interested at the moment, but feel free to follow up in Q3.",
            "campaigns": "General Outreach",
            "account": "Beta Inc."
        },
    ]
    send_reply_notification(sample_replies)
