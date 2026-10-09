"""Rule-based reply classification — local, deterministic, no external service.

Returns (category, source) where source is 'auto' when a rule matched with
enough confidence and 'manual' is reserved for user choices. Ambiguous text
stays 'unclassified' rather than guessing.
"""
import re


def _has(text: str, *patterns: str) -> bool:
    return any(re.search(p, text, re.IGNORECASE) for p in patterns)


def suggest_category(message: str) -> tuple[str, str]:
    """Classify one reply message. Returns (category, 'auto'|'unclassified')."""
    text = (message or '').strip()
    if not text:
        return 'unclassified', 'unclassified'
    low = text.lower()

    # Explicit opt-out wins over everything.
    if _has(low,
            r'\bunsubscribe\b', r'\bopt[ -]?out\b', r'\bdo not contact\b',
            r"\bdon'?t contact me\b", r'\bremove me\b', r'\btake me off\b',
            r'\bno further emails\b', r'\bstop (emailing|contacting) me\b'):
        return 'unsubscribe', 'auto'

    # Out-of-office / autoresponders (often mention dates or alternates).
    if _has(low,
            r'\bout of (the )?office\b', r'\bautomatic (reply|response)\b',
            r'\bauto[- ]response\b', r'\bi am (on )?(vacation|annual leave|maternity leave|sabbatical)\b',
            r'\baway from (the office|my desk)\b', r'\breturning (on|from)\b',
            r'\bwill be out\b.*\b(until|through|returning)\b'):
        return 'ooo', 'auto'

    # Declined / not interested — explicit negatives take priority over booking phrases.
    if _has(low,
            r'\bnot interested\b', r"\bno (thanks|thank you|interest)\b",
            r"\bwon'?t be (a fit|interested)\b", r'\bpass(ing)? on this\b',
            r'\bnot (a )?(good )?fit\b', r'\bdecline', r'\bwe are all set\b',
            r"\bwe'?re all set\b", r'\bno need\b', r'\bplease stop\b'):
        return 'declined', 'auto'

    # Meeting / booking intent.
    if _has(low,
            r'\b(book|schedule|set up|setup|arrange)\b.*\b(call|meeting|intro|introductory|demo)\b',
            r'\b(call|meeting|demo)\b.*\b(book|schedule|set up)\b',
            r'\bcalendly\b', r'\bcal\.com\b', r'\bbook a slot\b', r'\bmy calendar\b',
            r'\bhappy to (do|have) a call\b', r'\bopen to a (call|chat|meeting)\b',
            r'\b(when are you|what time).*\b(available|free)\b'):
        return 'meeting', 'auto'

    # Referral: points at another person.
    if _has(low,
            r'\b(colleague|coworker|counterpart|teammate)\b.*\b(handles?|owns?|in charge|cc.?ing|looping in|connect you with|reach out to)\b',
            r'\b(cc.?ing|looping in|forward(ed)? (this )?to)\b',
            r'\bconnect(ing)? you with\b', r'\btalk to\b.*\b(about this|instead)\b',
            r'\bbetter (person|contact)\b.*\bwould be\b'):
        return 'referral', 'auto'

    # "Follow up later": interested but timing is wrong.
    if _has(low,
            r'\b(follow up|circle back|reach out|get back|connect)\b.*\b(next (month|quarter|year)|later|in \d+ (weeks?|months?)|after (the )?(holidays|quarter))\b',
            r'\b(next (month|quarter|year)|later (this|next) (month|quarter|year))\b.*\b(follow|reach|talk|connect|circle)\b',
            r'\bnot (a )?(good|right) time\b', r'\brevisit\b', r'\bcatch (up|back) (in|after)\b',
            r'\bcheck back\b'):
        return 'followup_later', 'auto'

    # Positive / interested: asks for more info or expresses interest.
    if _has(low,
            r'\b(send|share) (me )?(more )?(details|info|information|deck|pricing)\b',
            r'\binterested\b', r'\bsounds (interesting|good|great)\b',
            r'\bwould (like|love) to (learn|know|hear)\b', r'\btell me more\b',
            r'\bcurious about\b', r'\blet.?s (talk|chat|connect|discuss)\b',
            r'\bhappy to (chat|discuss|connect)\b'):
        return 'positive', 'auto'

    return 'unclassified', 'unclassified'


CATEGORY_LABELS = {
    'positive': 'Positive / Interested',
    'meeting': 'Meeting requested',
    'followup_later': 'Follow up later',
    'referral': 'Referral',
    'declined': 'Declined / Not interested',
    'unsubscribe': 'Unsubscribe / Do not contact',
    'ooo': 'Out of office',
    'unclassified': 'Unclassified',
}

# Tone mapping used by the UI pills (kept in one place for parity).
CATEGORY_TONES = {
    'positive': 'ok', 'meeting': 'ok', 'followup_later': 'warn',
    'referral': 'primary', 'declined': 'crit', 'unsubscribe': 'crit',
    'ooo': 'idle', 'unclassified': 'idle',
}
