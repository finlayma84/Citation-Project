"""
Pass 1: Build a composer dictionary by mining the existing database.
"""

import sqlite3
import re
import unicodedata
from collections import defaultdict, Counter

DB_PATH = 'repertoire.db'


def strip_accents(s):
    return ''.join(c for c in unicodedata.normalize('NFD', s)
                   if unicodedata.category(c) != 'Mn')


def strip_arr_prefix(name):
    is_arr = False
    n = name.strip()
    for prefix in ('arr.', 'Arr.', 'arr ', 'Arr ', 'arranged by ', 'Arranged by '):
        if n.lower().startswith(prefix.lower()):
            is_arr = True
            n = n[len(prefix):].strip()
            break
    return n, is_arr


def strip_parenthetical(name):
    """'Mark Hayes (choir)' -> 'Mark Hayes' — drop trailing parentheticals."""
    return re.sub(r'\s*\([^)]*\)\s*$', '', name).strip()


def looks_like_composer(text):
    if not text:
        return False
    t = text.strip().rstrip(',').strip()
    word_count = len(t.split())
    if word_count > 6 or word_count == 0:
        return False
    title_indicators = ['Op.', 'Op ', 'No.', 'No ', 'BWV', 'K.', 'K ', '"', '"', '"']
    if any(ind in t for ind in title_indicators):
        return False
    letter_count = sum(c.isalpha() for c in t)
    if letter_count < len(t) * 0.5:
        return False
    first = t.split()[0]
    if not first[0].isupper():
        return False
    return True


def normalize_name_key(name):
    """Lowercased, accents stripped, initials dropped, parentheticals removed."""
    n = strip_parenthetical(name)
    n = strip_accents(n)
    n = n.lower().replace('.', '').strip()
    parts = n.split()
    parts = [p for p in parts if len(p) > 1]
    return ' '.join(parts)


def last_name_key(name):
    nk = normalize_name_key(name)
    if not nk:
        return ''
    return nk.split()[-1]


def name_quality_score(name):
    """Higher = better canonical choice.

    Penalize names containing catalog numbers, opus numbers, title fragments —
    these mean the parser dumped title material into the composer field.
    """
    score = 0
    # Real names tend to be 2-3 words
    parts = name.split()
    if 2 <= len(parts) <= 4:
        score += 10
    # Penalize obvious title-fragment leakage
    junk_patterns = [
        r'\bOp\b', r'\bNo\b', r'\bBWV\b', r'\bHob\b',
        r'\bK\.', r'\bD\.', r'[ivxIVX]+\b',  # roman numerals
        r'\d',           # any digit at all
        r'[\u2013\u2014]',   # en/em dashes (often in titles)
    ]
    for pat in junk_patterns:
        if re.search(pat, name):
            score -= 5
    # Reward names that look like pure people (only letters, periods, spaces, hyphens)
    if re.match(r'^[A-Za-zÀ-ÿ\s\.\-\']+$', name):
        score += 5
    # Slight bonus for length — fuller names often beat initialized ones
    score += min(len(name), 30) * 0.1
    return score


def extract_dates_from_field(dates_str):
    if not dates_str:
        return None, None
    s = dates_str.strip()
    if s.lower().startswith('b.'):
        m = re.search(r'(\d{4})', s)
        return (int(m.group(1)), None) if m else (None, None)
    m = re.match(r'(\d{4})\s*[-–]\s*(\d{4})', s)
    if m:
        return int(m.group(1)), int(m.group(2))
    m = re.match(r'(\d{4})\s+(\d{4})', s)
    if m:
        return int(m.group(1)), int(m.group(2))
    m = re.search(r'(\d{4})', s)
    return (int(m.group(1)), None) if m else (None, None)


def pick_best_dates(date_readings):
    """Pick most-common date pair. If no majority, accept a strong plurality."""
    if not date_readings:
        return (None, None), 0, False
    counter = Counter(date_readings)
    most_common = counter.most_common()
    top, top_count = most_common[0]
    total = sum(counter.values())
    # Accept the top pick if it's at least 50% of total or appears 3+ times
    if top_count / total >= 0.5 or top_count >= 3:
        return top, top_count, False
    return top, top_count, True   # ambiguous


# ---- Build ---------------------------------------------------------------

conn = sqlite3.connect(DB_PATH)
conn.row_factory = sqlite3.Row

rows = conn.execute(
    "SELECT composer, composer_dates FROM pieces WHERE chosen_by='Michael' AND composer != ''"
).fetchall()

groups = defaultdict(list)
rejected_count = 0
for r in rows:
    comp_raw = r['composer'].strip()
    base, is_arr = strip_arr_prefix(comp_raw)
    base = strip_parenthetical(base)
    if not looks_like_composer(base):
        rejected_count += 1
        continue
    key = last_name_key(base)
    if not key:
        rejected_count += 1
        continue
    groups[key].append({
        'raw': comp_raw,
        'base': base,
        'is_arr': is_arr,
        'dates': r['composer_dates'] or '',
    })

canonical = []
for key, entries in groups.items():
    # Pick the canonical name using quality score, breaking ties by frequency
    base_counts = Counter(e['base'] for e in entries)
    best_base = max(
        base_counts.items(),
        key=lambda kv: (name_quality_score(kv[0]), kv[1])
    )[0]

    date_readings = [
        extract_dates_from_field(e['dates'])
        for e in entries
        if extract_dates_from_field(e['dates']) != (None, None)
    ]
    best_dates, dates_count, ambiguous = pick_best_dates(date_readings)

    variants = sorted(set(e['raw'] for e in entries))
    date_variants = sorted(set(e['dates'] for e in entries if e['dates']))

    canonical.append({
        'key': key,
        'name': best_base,
        'birth': best_dates[0],
        'death': best_dates[1],
        'occurrences': len(entries),
        'name_variants': variants,
        'date_variants': date_variants,
        'date_ambiguous': ambiguous,
        'date_conflict': len(set(date_readings)) > 1,
    })

canonical.sort(key=lambda c: -c['occurrences'])

# ---- Report --------------------------------------------------------------

print(f"\n{'='*72}")
print(f"Mined {len(rows)} composer fields; rejected {rejected_count} that didn't look like names.")
print(f"Identified {len(canonical)} unique composers.\n")
print('='*72)

print("\n--- TOP 20 BY FREQUENCY ---\n")
for c in canonical[:20]:
    dates = ''
    if c['birth'] and c['death']:
        dates = f"({c['birth']}-{c['death']})"
    elif c['birth']:
        dates = f"(b. {c['birth']})"
    print(f"  {c['occurrences']:3}x  {c['name']:30}  {dates}")

print("\n--- MERGES (composers appearing under multiple spellings) ---\n")
n_merges = 0
for c in canonical:
    if len(c['name_variants']) > 1:
        n_merges += 1
        print(f"  → {c['name']}")
        for v in c['name_variants']:
            print(f"      • {v}")
print(f"\n  {n_merges} composers will be merged across spelling variants.")

print("\n--- DATE CONFLICTS ---\n")
n_conflicts = 0
n_ambiguous = 0
for c in canonical:
    if c['date_conflict']:
        n_conflicts += 1
        if c['date_ambiguous']:
            n_ambiguous += 1
            print(f"  ⚠ {c['name']}: variants {c['date_variants']} — AMBIGUOUS, not picking")
        else:
            chosen = f"{c['birth']}-{c['death']}" if c['birth'] and c['death'] else f"b. {c['birth']}"
            print(f"    {c['name']}: variants {c['date_variants']} — picking {chosen}")
print(f"\n  {n_conflicts} composers had conflicting dates; {n_ambiguous} were too ambiguous to auto-pick.")

print("\n--- LIKELY TYPOS ---\n")
from difflib import SequenceMatcher
high_freq = [c for c in canonical if c['occurrences'] >= 3]
low_freq = [c for c in canonical if c['occurrences'] == 1]
n_typos = 0
for low in low_freq:
    for high in high_freq:
        if low['key'] == high['key']:
            continue
        sim = SequenceMatcher(None, low['name'].lower(), high['name'].lower()).ratio()
        if sim > 0.85:
            n_typos += 1
            print(f"  '{low['name']}' (1x) ≈ '{high['name']}' ({high['occurrences']}x)?")
            break
print(f"\n  {n_typos} possible typos worth a human look.")

import json
with open('composer_dict.json', 'w') as f:
    json.dump([{
        'key': c['key'], 'name': c['name'],
        'birth': c['birth'], 'death': c['death'],
        'name_variants': c['name_variants'],
        'date_variants': c['date_variants'],
        'occurrences': c['occurrences'],
        'date_ambiguous': c['date_ambiguous'],
    } for c in canonical], f, indent=2, ensure_ascii=False)
print(f"\nSaved canonical dictionary to composer_dict.json ({len(canonical)} entries).")

conn.close()