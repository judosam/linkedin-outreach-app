"""Shared, bounded Google Chat message formatting (no network or secrets).

Modern outcome-first card:
- Expressive status badges & emojis (✨, ⚡, 🚀, 📥, 📬, 🛡️, ⚠️, 🚫)
- Clean meta details (🎯 Target, ⏱️ Runtime)
- Visual metric cards with distinct icons (✉️ Invites, ⚡ InMails, 💬 Messages, 🤝 Accepts, ⏳ Queue)
- Deduplicated import summaries & friendly error badges
- Standby / safety budget awareness
"""
import re

LABELS = {
    'sync_leads': 'Import SavedSearch',
    'import_list': 'Import SavedList',
    'send_connections': 'Connections',
    'send_followups': 'Follow-ups',
    'check_replies': 'Check Replies',
}

STATUS_VERBS = {
    'running': 'Started',
    'success': 'Completed',
    'error': 'Failed',
    'partial': 'Completed with warnings',
    'stopped': 'Stopped',
}

ICONS = {
    'running': '▶',
    'success': '✅',
    'error': '🚫',
    'partial': '⚠️',
    'stopped': '⏹',
    'info': 'ℹ️',
}

ACCOUNT_STAT_LABELS = {
    'contacted': 'Contacted',
    'invites_sent': 'Invites sent',
    'inmails_sent': 'InMails sent',
    'opentomsg_checked': 'Profiles checked',
    'leftover': 'Left for next run',
    'accepts_messaged': 'Accepts messaged',
    'new_replies': 'New replies',
    'replies_found': 'Replies found',
    'followups_sent': 'Follow-ups sent',
    'messages_sent': 'Messages sent',
    'leads_added': 'New leads added',
    'new_leads': 'New leads added',
}

STAT_EMOJIS = {
    'invites_sent': '✉️',
    'inmails_sent': '⚡',
    'contacted': '👥',
    'opentomsg_checked': '👥',
    'leftover': '⏳',
    'accepts_messaged': '🤝',
    'new_replies': '💬',
    'replies_found': '💬',
    'followups_sent': '💬',
    'messages_sent': '💬',
    'leads_added': '👥',
    'new_leads': '👥',
}

ALWAYS_SHOW_STAT_KEYS = {'invites_sent', 'inmails_sent'}

ACCOUNT_STAT_VERBS = {
    'accepts_messaged': ('invite accept', 'invite accepts', 'messaged'),
    'new_replies': ('new reply', 'new replies', 'received'),
    'replies_found': ('reply', 'replies', 'found'),
}


def clean(value):
    return str(value).replace('`', "'").replace('*', '').replace('\r', '').strip()


def title_case_key(key):
    """'invites_sent' → 'Invites sent'; known account keys win."""
    return ACCOUNT_STAT_LABELS.get(key, clean(key).replace('_', ' ').title())


def _is_zero(value):
    """True for 0, '0', '', None, 0.0 — anything meaning 'nothing happened'."""
    text = str(value).strip().lower()
    try:
        return float(text or 0) == 0
    except ValueError:
        return text in ('', 'none', 'null', 'nan', 'undefined')


def _plural_verb_line(key, count):
    """'accepts_messaged', 1 → '1 invite accept messaged'; 2 → '2 invite accepts messaged'."""
    singular, plural, verb = ACCOUNT_STAT_VERBS[key]
    return f'{count} {singular if count == 1 else plural} {verb}'


def _clean_error(err_str):
    """Format cryptic errors (HTTP 400 JSON dumps) into human-friendly explanations."""
    text = clean(err_str)
    if 'HTTP 400: {"value":"-1"}' in text or '{"value":"-1"}' in text:
        text = re.sub(r'HTTP 400:\s*\{"value":\s*"-1"\}\s*(\(request rejected\))?',
                      'Invite rejected by LinkedIn (weekly limit or profile privacy)', text)
    if 'no Sales Navigator seat' in text:
        text = text.replace('no Sales Navigator seat', 'No Sales Navigator seat assigned')
    return text.strip()


def _format_account_stats(stats):
    """Format per-account dictionary stats with clean emoji indicators."""
    if not isinstance(stats, dict):
        return clean(stats)[:400]

    friendly = []
    invites = stats.get('invites_sent')
    inmails = stats.get('inmails_sent')

    for key, value in stats.items():
        if key not in ACCOUNT_STAT_LABELS:
            continue
        if _is_zero(value) and key not in ALWAYS_SHOW_STAT_KEYS:
            continue
        text = clean(value)
        emoji = STAT_EMOJIS.get(key, '')
        prefix = f'{emoji} ' if emoji else ''
        label = ACCOUNT_STAT_LABELS[key]

        if '/' in text and ' ' not in text:
            friendly.append(f'{prefix}{label}: {text}')
        elif key in ACCOUNT_STAT_VERBS and str(value).strip().isdigit():
            friendly.append(f'{prefix}{_plural_verb_line(key, int(value))}')
        else:
            friendly.append(f'{prefix}{label}: {text}')

    return ' · '.join(friendly)


def format_duration(seconds):
    """'0.0s → 2m 15s → 1h 04m' — human, not '135.0s'."""
    try:
        seconds = max(0.0, float(seconds))
    except (TypeError, ValueError):
        return ''
    if seconds < 60:
        return f'{seconds:.1f}s'
    minutes, sec = divmod(int(seconds), 60)
    if minutes < 60:
        return f'{minutes}m {sec:02d}s'
    hours, minutes = divmod(minutes, 60)
    return f'{hours}h {minutes:02d}m'


def _format_import_summary(metrics):
    """Consolidates repetitive scraper/import keys into a modern, 2-line summary."""
    if not isinstance(metrics, dict):
        return None
    import_keys = {'page', 'page_extracted', 'extracted', 'added', 'total', 'total_pages', 'percent', 'new_leads'}
    if not any(k in metrics for k in import_keys):
        return None

    new_leads = metrics.get('new_leads')
    if new_leads is None:
        new_leads = metrics.get('added') or metrics.get('extracted') or 0
    page = metrics.get('page') or metrics.get('page_extracted') or 1
    total_pages = metrics.get('total_pages') or page
    pct = metrics.get('percent')
    if pct is None and total_pages:
        try:
            pct = min(100, round((int(page) / int(total_pages)) * 100))
        except (ValueError, ZeroDivisionError):
            pct = 100

    lines = [
        '📊 *Import Summary:*',
        f'  👥 *New Leads Added:* {clean(new_leads)} leads',
        f'  📄 *Pages Processed:* {clean(page)} / {clean(total_pages)} ({pct}% complete)',
        '✅ *Status:* All leads tagged and ready for outreach.',
    ]
    return lines


def message(title, status, context='', metrics=None, errors=None, duration=None):
    """Build the modern outcome-first Google Chat card."""
    status_str = clean(status).lower()
    title_key = clean(title)
    label = LABELS.get(title_key, clean(title_key).replace('_', ' ').title())

    # Detect standby run (connections job where nothing was sent)
    is_standby = False
    is_inmail_only = False
    if title_key == 'send_connections' and status_str in ('success', 'partial'):
        total_inv = 0
        total_inm = 0
        has_stats = False
        if isinstance(metrics, dict):
            for k, v in metrics.items():
                if isinstance(v, dict):
                    has_stats = True
                    try:
                        total_inv += float(v.get('invites_sent', 0) or 0)
                        total_inm += float(v.get('inmails_sent', 0) or 0)
                    except (ValueError, TypeError):
                        pass
        if has_stats and total_inv == 0 and total_inm == 0:
            is_standby = True
        elif has_stats and total_inv == 0 and total_inm > 0:
            is_inmail_only = True

    # Expressive Header
    if is_standby:
        header = '🛡️ *Campaign Manager* • *Connections Standby*'
    elif title_key in ('sync_leads', 'import_list'):
        ic = '📥' if status_str in ('success', 'partial') else ICONS.get(status_str, '📥')
        v = 'Import Completed' if status_str == 'success' else ('Import SavedList (Action Needed)' if status_str == 'partial' else f'Import {STATUS_VERBS.get(status_str, status_str.title())}')
        header = f'{ic} *Campaign Manager* • *{v}*'
    elif is_inmail_only:
        ic = '⚡' if status_str == 'success' else ('⚠️' if status_str == 'partial' else '🚫')
        v = 'InMail Outreach Completed' if status_str == 'success' else 'InMail Outreach (Action Needed)'
        header = f'{ic} *Campaign Manager* • *{v}*'
    elif title_key == 'send_connections':
        if status_str == 'partial':
            header = '⚠️ *Campaign Manager* • *Connections (Action Needed)*'
        elif status_str == 'error':
            header = '🚫 *Campaign Manager* • *Connections Failed*'
        else:
            header = '✨ *Campaign Manager* • *Connections Completed*'
    elif title_key == 'send_followups':
        if status_str == 'partial':
            header = '⚠️ *Campaign Manager* • *Follow-ups (Action Needed)*'
        elif status_str == 'error':
            header = '🚫 *Campaign Manager* • *Follow-ups Failed*'
        else:
            header = '🚀 *Campaign Manager* • *Follow-ups Completed*'
    elif title_key == 'check_replies':
        if status_str == 'partial':
            header = '⚠️ *Campaign Manager* • *Check Replies (Action Needed)*'
        elif status_str == 'error':
            header = '🚫 *Campaign Manager* • *Check Replies Failed*'
        else:
            header = '📬 *Campaign Manager* • *Check Replies Completed*'
    else:
        ic = ICONS.get(status_str, 'ℹ️')
        v = STATUS_VERBS.get(status_str, status_str.title())
        header = f'{ic} *Campaign Manager · {label}*'

    lines = [header]

    # Status subtitle for clarity / test compatibility
    if status_str == 'success':
        lines.append('✅ *Completed*')
    elif status_str == 'partial':
        lines.append('⚠️ *Completed with warnings*')
    elif status_str in ('error', 'stopped'):
        lines.append(f"{ICONS.get(status_str, 'ℹ️')} *{STATUS_VERBS.get(status_str, status_str.title())}*")

    # Meta context & duration
    meta = []
    if context:
        meta.append(clean(context)[:200])
    if duration is not None:
        dur = format_duration(duration)
        if dur:
            meta.append(dur)
    if meta:
        lines.append(' · '.join(meta))

    # Check for consolidated import summary
    import_summary = _format_import_summary(metrics) if title_key in ('sync_leads', 'import_list') or (isinstance(metrics, dict) and 'action' in metrics) else None
    if import_summary:
        lines.extend(import_summary)
    else:
        # Standard metrics formatting
        for key, value in list((metrics or {}).items())[:14]:
            if isinstance(value, dict):
                val_str = _format_account_stats(value)
                if not val_str:
                    continue  # idle/no-op account: omit
                lines.append(f'*{clean(key)}* — {val_str}')
            else:
                if _is_zero(value):
                    continue  # top-level zero metrics: hide
                emoji = STAT_EMOJIS.get(key, '')
                prefix = f'{emoji} ' if emoji else ''
                lines.append(f'{prefix}{title_case_key(key)}: {clean(value)[:400]}')

    # Standby budget note
    if is_standby:
        lines.append('🔒 *Budget Status:* Weekly limit or safety interval active (No actions needed)')

    # Friendly attention / errors block
    if errors:
        counts = {}
        for error in errors:
            cleaned = _clean_error(error)[:400]
            counts[cleaned] = counts.get(cleaned, 0) + 1
        lines.append('⚠️ *Attention needed:*')
        lines.extend(f'  • 🚫 {err}' + (f' (×{n})' if n > 1 else '')
                     for err, n in list(counts.items())[:6])

    return '\n'.join(lines)[:6000]
