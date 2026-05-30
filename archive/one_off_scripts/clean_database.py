"""
Pass 2: Apply the composer dictionary to clean up the database.

Reads composer_dict.json (produced by build_composer_dict.py).
Backs up repertoire.db to repertoire.db.backup before any changes.
"""

import sqlite3
import shutil
import json
import re
import unicodedata
from pathlib import Path

DB_PATH = 'repertoire.db'
BACKUP_PATH = 'repertoire.db.backup'
DICT_PATH = 'composer_dict.json'


def strip_accents(s):
    return ''.join(c for c in unicodedata.normalize('NFD', s)
                   if unicodedata.category(c) != 'Mn')


def normalize_key(s):
    """Same normalization as the dictionary builder uses."""
    s = re.sub(r'\s*\([^)]*\)\s*$', '', s).strip()   # strip parenthetical
    s = strip_accents(s).lower().replace('.', '').strip()
    # Drop initials
    parts = [p for p in s.split() if len(p) > 1]
    return ' '.join(parts)


def last_name_of(s):
    nk = normalize_key(s)
    return nk.split()[-1] if nk else ''


def pick_cleanest_variant(variants):
    """Choose the most name-like variant from a list. Reject ones with title leakage."""
    def score(v):
        s = 0
        # Prefer shorter (less likely to be title + composer)
        s -= len(v) * 0.5
        # Heavily penalize obvious junk
        if 'arr' in v.lower():
            s -= 30
        if re.search(r'\d', v):
            s -= 30
        if re.search(r'[\u2013\u2014:/]', v):
            s -= 20
        if '(' in v:
            s -= 10
        # Prefer 2-3 word names
        parts = v.split()
        if 2 <= len(parts) <= 4:
            s += 10
        return s
    return max(variants, key=score)


def strip_arr(name):
    """'arr. Mark Hayes' -> 'Mark Hayes', plus a flag."""
    n = name.strip()
    for prefix in ('arr.', 'Arr.', 'arr ', 'Arr ', 'arranged by ', 'Arranged by '):
        if n.lower().startswith(prefix.lower()):
            return n[len(prefix):].strip(), True
    return n, False


# ---- Load dictionary -----------------------------------------------------

with open(DICT_PATH) as f:
    raw_dict = json.load(f)

# Build several lookup tables: by last-name key, by full name key, with cleanest display name
by_key = {}
for entry in raw_dict:
    cleanest = pick_cleanest_variant(entry['name_variants'])
    by_key[entry['key']] = {
        'display': cleanest,
        'birth': entry['birth'],
        'death': entry['death'],
        'date_ambiguous': entry.get('date_ambiguous', False),
        'occurrences': entry['occurrences'],
    }

# Also a last-name lookup (the key) -> for finding composers embedded in title strings
last_name_lookup = {entry['key']: entry['key'] for entry in raw_dict}

print(f"Loaded dictionary with {len(by_key)} composer entries.\n")


# ---- Back up database ----------------------------------------------------

if Path(BACKUP_PATH).exists():
    print(f"Note: {BACKUP_PATH} already exists; overwriting.")
shutil.copy(DB_PATH, BACKUP_PATH)
print(f"Backed up {DB_PATH} → {BACKUP_PATH}\n")


# ---- Clean rows -----------------------------------------------------------

conn = sqlite3.connect(DB_PATH)
conn.row_factory = sqlite3.Row
rows = conn.execute(
    "SELECT id, composer, composer_dates, title FROM pieces WHERE chosen_by='Michael'"
).fetchall()

stats = {
    'normalized_composer': 0,
    'title_leak_fixed': 0,
    'dates_overridden': 0,
    'untouched': 0,
}

for row in rows:
    rid = row['id']
    orig_composer = row['composer'] or ''
    orig_dates = row['composer_dates'] or ''
    orig_title = row['title'] or ''

    new_composer = orig_composer
    new_dates = orig_dates
    changed = False

    # Try to find the composer in the dictionary
    base, was_arr = strip_arr(orig_composer)
    ln = last_name_of(base)
    entry = by_key.get(ln)

    if entry:
        # Step 1: normalize the composer field to the cleanest variant
        prefix = 'arr. ' if was_arr else ''
        clean = prefix + entry['display']
        if clean != orig_composer:
            new_composer = clean
            stats['normalized_composer'] += 1
            changed = True

        # Step 3: override dates if dictionary is confident
        if not entry['date_ambiguous'] and entry['birth'] and entry['occurrences'] >= 3:
            if entry['death']:
                ideal = f"{entry['birth']}-{entry['death']}"
            else:
                ideal = f"b. {entry['birth']}"
            if orig_dates != ideal and (not orig_dates or
                                         orig_dates != f"{entry['birth']}–{entry['death']}"):
                new_dates = ideal
                stats['dates_overridden'] += 1
                changed = True

    else:
        # Step 2: title-leak detection. Composer field has no recognized name —
        # try to find a known composer's last name *inside* the composer string.
        words = orig_composer.split()
        for i in range(len(words)):
            candidate_ln = last_name_of(words[i])
            if candidate_ln in by_key:
                # Found one; the composer field is "<title fragment> <composer name>"
                # — assume the dictionary entry IS the composer
                ent = by_key[candidate_ln]
                new_composer = ent['display']
                if not orig_dates and ent['birth'] and not ent['date_ambiguous']:
                    if ent['death']:
                        new_dates = f"{ent['birth']}-{ent['death']}"
                    else:
                        new_dates = f"b. {ent['birth']}"
                stats['title_leak_fixed'] += 1
                changed = True
                break

    if changed:
        conn.execute(
            "UPDATE pieces SET composer=?, composer_dates=? WHERE id=?",
            (new_composer, new_dates, rid)
        )
    else:
        stats['untouched'] += 1

conn.commit()
conn.close()


# ---- Report --------------------------------------------------------------

print("Done. Summary of changes:")
print(f"  {stats['normalized_composer']:4} composer names normalized to dictionary spelling")
print(f"  {stats['title_leak_fixed']:4} title-leak cases fixed (composer found inside garbage field)")
print(f"  {stats['dates_overridden']:4} composer date fields overridden from dictionary")
print(f"  {stats['untouched']:4} rows untouched\n")

print(f"Original database backed up at {BACKUP_PATH}.")
print(f"To restore: cp {BACKUP_PATH} {DB_PATH}")