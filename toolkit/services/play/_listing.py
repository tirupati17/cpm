"""Play store listing text checks. Pure logic, no network and no secrets.

Play ranks title > short description > full description for search, and,
unlike the App Store, indexes the full description. Put the phrase people
search in the title, the second set of terms in the short description, and
repeat the core terms naturally in the full description, never as a keyword
list, which Play penalises.
"""
import re

LIMITS = {'title': 30, 'shortDescription': 80, 'fullDescription': 4000}
# Play's metadata policy: no ranking, price or call-to-action claims in the title.
# Lookarounds, not \b: '#1' starts with a non-word character, so \b#1 never matches.
BANNED_IN_TITLE = re.compile(r'(?<!\w)(best|#1|no\.? ?1|top|free|new|sale|discount|download|install|app of the year)(?!\w)', re.I)
EMOJI = re.compile('[\U0001F300-\U0001FAFF☀-➿]')
DASHES = ('—', '–')


def problems(copy, forbid_dashes=False):
    """Everything wrong with one language's copy, as readable strings."""
    found = []
    for field, limit in LIMITS.items():
        value = copy.get(field, '')
        if not value.strip():
            found.append(f'{field} is empty')
        elif len(value) > limit:
            found.append(f'{field} is {len(value)} characters, limit {limit}')
        if forbid_dashes and any(d in value for d in DASHES):
            found.append(f'{field} has an em/en dash')
    title = copy.get('title', '')
    if BANNED_IN_TITLE.search(title):
        found.append(f'title has a ranking/price word: {BANNED_IN_TITLE.search(title).group(0)!r}')
    if EMOJI.search(title):
        found.append('title has an emoji')
    if any(len(w) > 3 and w.isupper() and w.isalpha() for w in re.findall(r'\w+', title)):
        found.append('title has an all-caps word')
    return found


def changes(current, copy):
    """The listing fields that differ from what Play has now."""
    return [f for f in LIMITS if (current or {}).get(f, '').strip() != copy.get(f, '').strip()]
