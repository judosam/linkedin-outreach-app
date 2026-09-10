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

from .database import SessionLocal
from .models import NotificationSettings

# Server-side SMTP config (env only - deliberately NOT user-editable in the UI,
# per the spec: "the SMTP sender itself can stay server-side config").
SMTP_SERVER = 'smtp.gmail.com'
SMTP_PORT = 587
SMTP_SENDER = 'samuel@vservesolution.com'
SMTP_PASSWORD = 'qyrg jkbx sasr aipo'  # loaded from env at import (see below)
import os
SMTP_PASSWORD = os.environ.get('NOTIFY_SENDER_APP_PASSWORD', SMTP_PASSWORD)
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
    return get_settings().gchat_webhook_url or ENV_WEBHOOK


def _flags():
    s = get_settings()
    return {
        'critical': s.alert_critical,
        'run_summary': s.alert_run_summary,
        'send_errors': s.alert_send_errors,
        'reply_digest': s.alert_reply_digest,
    }


def _is_nonzero(value):
    text = str(value).strip()
    number_part = text.split('/')[0].strip() if '/' in text else text
    try:
        return float(number_part) != 0
    except ValueError:
        return bool(text)


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
    text = f"🚨 *CRITICAL ERROR*\n👤 Account: *{account}*\n\n```{str(error)[:800]}```"
    return send_gchat(text)


def notify_send_errors(account, errors):
    """⚠️ Deduplicated send-error digest: identical errors collapse to '(xN)'."""
    if not errors or not _flags()['send_errors']:
        return None
    counts = {}
    for e in errors:
        counts[e] = counts.get(e, 0) + 1
    lines = '\n'.join(f"- {msg} (x{n})" if n > 1 else f"- {msg}" for msg, n in counts.items())
    text = f"⚠️ *Send Errors*\n👤 Account: *{account}*\n\n{lines}"
    return send_gchat(text)


def notify_run_summary(all_stats):
    """🎉 One summary per run; zero-activity entries omitted."""
    if not _flags()['run_summary']:
        return None
    blocks = []
    for target, stats in (all_stats or {}).items():
        active = {k: v for k, v in (stats or {}).items() if _is_nonzero(v)}
        if not active:
            continue
        lines = '\n'.join(f"   - {label}: *{value}*" for label, value in active.items())
        blocks.append(f"👤 *{target}*\n{lines}")
    if not blocks:
        return None
    return send_gchat(f"🎉 *Run Complete*\n\n" + '\n\n'.join(blocks))


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
    if not replies or not _flags()['reply_digest']:
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
        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
            server.starttls()
            server.login(SMTP_SENDER, SMTP_PASSWORD)
            server.sendmail(SMTP_SENDER, recipients, msg.as_string())
        print(f"📧 Reply digest sent to {', '.join(recipients)}")
        return True
    except Exception as e:
        print(f"❌ Failed to send reply digest: {e}")
        return False
