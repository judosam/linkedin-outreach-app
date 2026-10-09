"""Notifications: Google Chat webhook alerts + HTML reply-digest email.

Settings live in notification_settings (DB) with env fallbacks. Every function
is fail-safe: a notification problem must never break a pipeline run.
"""
import json
import smtplib
from datetime import datetime
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from html import escape

import curl_cffi
from notification_format import message

from .database import SessionLocal
from .models import NotificationSettings

# Server-side SMTP config (env only - deliberately NOT user-editable in the UI,
# per the spec: "the SMTP sender itself can stay server-side config").
SMTP_SERVER = 'smtp.gmail.com'
SMTP_PORT = 587
SMTP_SENDER = 'samuel@vservesolution.com'
import os
SMTP_PASSWORD = os.environ.get('NOTIFY_SENDER_APP_PASSWORD', '')
SMTP_SENDER = os.environ.get('NOTIFY_SENDER_EMAIL', SMTP_SENDER)

ENV_WEBHOOK = os.environ.get('GCHAT_WEBHOOK_URL', '')
ENV_RECIPIENTS = [
    r.strip() for r in os.environ.get(
        'NOTIFY_RECIPIENT_EMAILS',
        'samuel@vservesolution.com,ranganathan@vservesolution.com,nandhini@vservesolution.com,prabhu@vservesolution.com'
    ).split(',') if r.strip()
]


def get_settings():
    """Single settings row, creating it on first access."""
    db = SessionLocal()
    try:
        row = db.get(NotificationSettings, 1)
        if row is None:
            row = NotificationSettings(
                id=1, gchat_webhook_url=ENV_WEBHOOK, email_recipients=ENV_RECIPIENTS)
            db.add(row)
            db.commit()
            db.refresh(row)
        return row
    finally:
        db.close()


def _webhook_url():
    return get_settings().gchat_webhook_url or ''


def _flags():
    s = get_settings()
    return {
        'critical': s.alert_critical,
        'run_summary': s.alert_run_summary,
        'send_errors': s.alert_send_errors,
        'reply_digest': s.alert_reply_digest,
    }


def _is_nonzero(value):
    if value is None:
        return False
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, dict):
        return any(_is_nonzero(v) for v in value.values())
    if isinstance(value, (list, tuple, set)):
        return any(_is_nonzero(v) for v in value)
    text = str(value).strip()
    if not text or text.lower() in ('none', 'null', 'nan', 'undefined'):
        return False
    number_part = text.split('/')[0].strip() if '/' in text else text
    try:
        return float(number_part) != 0
    except ValueError:
        return bool(text)


def _format_stat_value(v):
    if isinstance(v, dict):
        parts = [f"{k.replace('_', ' ')}: {val}" for k, val in v.items() if _is_nonzero(val)]
        return ', '.join(parts) if parts else '0'
    return str(v)


def send_gchat(text):
    url = _webhook_url()
    if not url:
        return False
    try:
        response = curl_cffi.post(url, json={'text': text}, timeout=10)
        ok = response.status_code in (200, 204)
        if not ok:
            print(f"⚠️ [G-Chat] Notification failed: {response.status_code} - {response.text[:200]}")
        return ok
    except Exception as e:
        print(f"⚠️ [G-Chat] Notification exception: {e}")
        return False


def notify_critical(account, error):
    """🚨 Immediate alert on a job's fatal exception."""
    if not _flags()['critical']:
        return None
    text = message('Worker alert', 'error', account, errors=[error])
    return send_gchat(text)


def notify_send_errors(account, errors):
    """⚠️ Standalone send-error digest (identical errors collapse via message()).

    NOTE: run completions must NOT call this — the lifecycle card emitted by
    notify_lifecycle() already embeds run.errors under 'Attention needed'.
    Calling both duplicated the 'Execution warnings' GChat cards.
    """
    if not errors or not _flags()['send_errors']:
        return None
    text = message('Execution warnings', 'partial', account, errors=errors)
    return send_gchat(text)


def notify_run_summary(all_stats):
    """🎉 Ad-hoc multi-target summary.

    NOTE: run completions must NOT call this — notify_lifecycle() already
    emits the single per-run completion card (stats + duration + errors);
    calling both duplicated every run completion in GChat.
    """
    if not _flags()['run_summary']:
        return None
    blocks = []
    for target, stats in (all_stats or {}).items():
        active = {k: v for k, v in (stats or {}).items() if _is_nonzero(v)}
        if not active:
            continue
        lines = '\n'.join(f"   - {label}: *{_format_stat_value(value)}*" for label, value in active.items())
        blocks.append(f"👤 *{target}*\n{lines}")
    if not blocks:
        return None
    return send_gchat(message('Run summary', 'success', metrics=all_stats))


_lifecycle_notified = set()


def reply_activity(stats):
    """Only confirmed messages/replies count, never labels or scanned totals."""
    if not isinstance(stats, dict):
        return False
    for key in ('accepts_messaged', 'new_replies'):
        try:
            if float(stats.get(key, 0)) > 0:
                return True
        except (TypeError, ValueError):
            pass
    return any(reply_activity(value) for value in stats.values() if isinstance(value, dict))


def notify_lifecycle(run):
    """Called at durable finish boundaries; never for a dry run.

    Emits ONE completion summary per run row — a second call for the same
    run (dedicated summary + _finish) is a no-op. Stopped runs stay silent:
    the operator who stopped the run watched it happen.
    """
    if run.dry_run:
        return False
    if getattr(run, 'status', '') == 'stopped':
        return False
    stats = run.stats
    if run.job_type == 'check_replies':
        if not reply_activity(stats):
            return False
        # Keep the saved run intact; omit inactive accounts from the Chat summary.
        stats = {key: value for key, value in stats.items()
                 if not isinstance(value, dict) or reply_activity(value)}
    key = getattr(run, 'id', None)
    if key is not None:
        if key in _lifecycle_notified:
            return False
        _lifecycle_notified.add(key)
    try:
        if not _flags()['run_summary']:
            return False
        return send_gchat(message(run.job_type, run.status, run.target,
                                 metrics=stats, errors=run.errors, duration=run.duration_s))
    except Exception:
        return False


def notify_new_replies(replies):
    """📬 Send Google Chat alert when new replies are detected from prospects."""
    if not replies:
        return None
    count = len(replies)
    plural = 'y' if count == 1 else 'ies'
    lines = [f"📬 *Campaign Manager · New replies* • *{count} New Repl{plural} Received!*"]
    
    # Identify primary campaign / account
    target = ""
    for r in replies:
        camp = r.get('campaign', '')
        acct = r.get('account', '')
        if camp or acct:
            target = f"{camp} / {acct}".strip(' /')
            break
    if target:
        lines.append(f"🎯 *Account:* {target}")
    
    for r in replies[:10]:
        name = r.get('name', 'Lead')
        msg = (r.get('message') or r.get('snippet') or '').strip().replace('\r\n', '\n').replace('\r', '\n')
        snippet = (msg[:250] + '…') if len(msg) > 250 else msg
        lines.append(f"\n👤 *{name}*\n  💬 _{snippet}_")
    
    lines.append("\n👉 *Action:* Reply directly in Sales Navigator or LinkedIn Inbox.")
    return send_gchat('\n'.join(lines))


# ================= HTML reply digest (mirrors email_notifier.py style) =================

def build_reply_digest_html(replies, today_str):
    cards = ''
    for r in replies:
        name = escape(r.get('name', 'Unknown Lead'))
        message = escape(r.get('message', '') or '')
        snippet = (message[:200] + '…') if len(message) > 200 else message
        campaigns = escape(r.get('campaign', 'General Outreach'))
        account = escape(r.get('account', 'Unknown Account'))
        initials = ''.join(p[0] for p in name.split()[:2]).upper() or 'L'
        cards += f"""
        <div style="background:#ffffff;border:1px solid #e8ecf3;border-radius:14px;padding:16px 18px;margin:0 0 12px 0;">
          <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0"><tr>
            <td width="48" style="vertical-align:top;padding-right:12px;">
              <div style="width:40px;height:40px;border-radius:50%;background:linear-gradient(135deg,#4F46E5,#7C3AED);color:#fff;font-size:15px;font-weight:700;text-align:center;line-height:40px;font-family:Arial,sans-serif;">{initials}</div>
            </td>
            <td style="vertical-align:top;">
              <div style="font-size:15px;font-weight:700;color:#0f172a;">{name}</div>
              <div style="margin-top:8px;background:#f8fafc;border-left:3px solid #6366f1;border-radius:10px;padding:10px 14px;font-size:14px;color:#334155;">&ldquo;{snippet}&rdquo;</div>
              <div style="margin-top:10px;">
                <span style="display:inline-block;background:#eef2ff;color:#4338ca;font-size:12px;font-weight:600;padding:3px 10px;border-radius:30px;">🎯 {campaigns}</span>
                <span style="display:inline-block;background:#f1f5f9;color:#475569;font-size:12px;font-weight:600;padding:3px 10px;border-radius:30px;">👤 {account}</span>
              </div>
            </td>
          </tr></table>
        </div>"""

    count = len(replies)
    plural = 'y' if count == 1 else 'ies'
    return f"""<!DOCTYPE html><html><body style="margin:0;padding:0;background:#f4f6fa;font-family:-apple-system,'Segoe UI',Roboto,Arial,sans-serif;">
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0" bgcolor="#f4f6fa"><tr><td align="center" style="padding:24px 12px;">
    <table role="presentation" width="800" cellpadding="0" cellspacing="0" style="max-width:800px;">
      <tr><td>
        <div style="background:#fff;border:1px solid #e8ecf3;border-radius:18px;overflow:hidden;">
          <div style="padding:32px 28px;background:linear-gradient(135deg,#1e1b4b 0%,#312E81 40%,#4F46E5 75%,#7C3AED 100%);text-align:center;">
            <div style="font-size:18px;">📬</div>
            <div style="color:#fff;font-size:24px;font-weight:800;">{count} new repl{plural}</div>
            <div style="color:rgba(255,255,255,.82);font-size:14px;margin-top:6px;">New responses from your LinkedIn outreach</div>
            <div style="display:inline-block;margin-top:12px;background:rgba(255,255,255,.16);border:1px solid rgba(255,255,255,.25);padding:5px 16px;border-radius:30px;color:#fff;font-size:12px;font-weight:600;">{today_str}</div>
          </div>
          <div style="padding:24px 28px;">{cards}</div>
        </div>
      </td></tr>
    </table>
  </td></tr></table>
</body></html>"""


def send_reply_digest(replies):
    """One HTML email per run listing every new reply. Returns True on success."""
    if not SMTP_PASSWORD or not replies or not _flags()['reply_digest']:
        return False
    settings = get_settings()
    recipients = settings.email_recipients or ENV_RECIPIENTS
    if not recipients:
        print('⚠️ No email recipients configured - reply digest skipped')
        return False
    today_str = datetime.now().strftime('%d %b %Y')
    count = len(replies)
    subject = f"🔔 {count} new LinkedIn repl{'y' if count == 1 else 'ies'} — {today_str}"

    msg = MIMEMultipart('alternative')
    msg['From'] = f'Linkedin Notification<{SMTP_SENDER}>'
    msg['To'] = ', '.join(recipients)
    msg['Subject'] = subject
    plain = '\n'.join(f"- {r.get('name')}: {(r.get('message') or '')[:150]}" for r in replies)
    msg.attach(MIMEText(plain, 'plain'))
    msg.attach(MIMEText(build_reply_digest_html(replies, today_str), 'html'))

    try:
        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT, timeout=30) as server:
            server.starttls()
            server.login(SMTP_SENDER, SMTP_PASSWORD)
            server.sendmail(SMTP_SENDER, recipients, msg.as_string())
        print(f"📧 Reply digest sent to {', '.join(recipients)}")
        return True
    except Exception as e:
        print(f"❌ Failed to send reply digest: {e}")
        return False
