import os
import curl_cffi
from collections import Counter

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# Webhook can be overridden via .env (GCHAT_WEBHOOK_URL); falls back to the
# original hardcoded value so existing Task Scheduler runs keep working.
GCHAT_WEBHOOK_URL = os.environ.get(
    'GCHAT_WEBHOOK_URL',
    'https://chat.googleapis.com/v1/spaces/AAQAjzH6Jic/messages?key=AIzaSyXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX&token=XXXX'
)

def send_gchat_message(text):
    """POST a plain text message to the configured Google Chat webhook. Never raises -
    a notification failure should never break the calling pipeline script."""
    try:
        response = curl_cffi.post(GCHAT_WEBHOOK_URL, json={'text': text}, timeout=10)
        if response.status_code not in (200, 204):
            print(f"⚠️ [G-Chat] Notification failed: {response.status_code} - {response.text[:200]}")
        return response.status_code in (200, 204)
    except Exception as e:
        print(f"⚠️ [G-Chat] Notification exception: {e}")
        return False

def _is_nonzero(value):
    """True if `value` represents an actual non-zero amount, so zero-activity lines
    (e.g. '0', '0/20') can be dropped from notifications instead of cluttering them."""
    text = str(value).strip()
    number_part = text.split('/')[0].strip() if '/' in text else text
    try:
        return float(number_part) != 0
    except ValueError:
        return bool(text)

def notify_critical(account, error):
    """🚨 Fire immediately from inside an except block when a pipeline step fails hard
    (session/auth errors, sheet write failures, unhandled exceptions, etc.)."""
    text = f"🚨 *CRITICAL ERROR*\n👤 Account: *{account}*\n\n```{str(error)[:800]}```"
    return send_gchat_message(text)

def notify_final_status(account, stats):
    """✅ Fire once a single account finishes its run. `stats` is an ordered dict of
    label -> value rendered as bullet lines, e.g. {'📩 Invites sent': '5/15'}. Zero/empty
    values are dropped - if nothing happened for this account, nothing is sent."""
    active_stats = {label: value for label, value in stats.items() if _is_nonzero(value)}
    if not active_stats:
        return None
    lines = '\n'.join(f"- {label}: *{value}*" for label, value in active_stats.items())
    text = f"👤 Account: *{account}*\n\n{lines}"
    return send_gchat_message(text)

def notify_run_summary(all_accounts_stats):
    """🎉 Fire once at the very end of the run, after every account has finished, with
    one block per account. `all_accounts_stats` is {account_name: {label: value, ...}}.
    Zero/empty stat lines are dropped, and an account is skipped entirely if every one
    of its values was zero (no activity to report)."""
    blocks = []
    for account, stats in all_accounts_stats.items():
        active_stats = {label: value for label, value in stats.items() if _is_nonzero(value)}
        if not active_stats:
            continue
        lines = '\n'.join(f"   - {label}: *{value}*" for label, value in active_stats.items())
        blocks.append(f"👤 *{account}*\n{lines}")
    if not blocks:
        return None
    body = '\n\n'.join(blocks)
    text = f"🎉 *Run Complete*\n\n{body}"
    return send_gchat_message(text)

def notify_send_errors(account, errors):
    """⚠️ Fire once per account with every non-200 API response hit during the run,
    consolidated instead of one message per failure. Identical errors are deduped and
    shown as a single line with a count, e.g. '429: rate limited (x4)'. `errors` is a
    flat list of raw error strings collected as they happen - pass the same list in,
    duplicates and all; the counting happens here."""
    if not errors:
        return None
    counts = Counter(errors)
    lines = '\n'.join(f"- {msg} (x{n})" for msg, n in counts.most_common())
    text = f"⚠️ *Send Errors*\n👤 Account: *{account}*\n\n{lines}"
    return send_gchat_message(text)

if __name__ == "__main__":
    send_gchat_message("🧪 *Test message* from `gchat_notifier.py` — webhook is wired up correctly ✅")
