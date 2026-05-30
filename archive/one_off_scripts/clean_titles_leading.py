"""
Pass 4: Strip composer name from the BEGINNING of title fields,
where the composer field correctly identifies the composer.
Skips cases where the composer is referenced via "by", "on", "after", etc.
"""

import sqlite3
import shutil
import json
import re
import unicodedata
from pathlib import Path

DB_PATH = 'repertoire.db'
BACKUP_PATH = 'repertoire.db.backup_pass4'
DICT_PATH = 'composer_dict.json'


def strip_accents(s):
    return ''.join(c for c in unicodedata.normalize('NFD', s)
                   if unicodedata.category(c) != 'Mn')


def normalize_key(s):
    s = re.sub(r'\s*\([^)]*\)\s*$', '', s).strip()
    s = strip_accents(s).lower().replace('.', '').strip()
    return ' '.join(p for p in s.split() if len(p) > 1)


def last_name_of(s):
    nk = normalize_key(s)
    return nk.split()[-1] if nk else ''


def strip_arr_prefix(name):
    n = name.strip()
    for prefix in ('arr.', 'Arr.', 'arr ', 'Arr ', 'arranged by ', 'Arranged by '):
        if n.lower().startswith(prefix.lower()):
            return n[len(prefix):].strip()
    return n


# Words immediately before a composer name that mean it's being *referenced*, not *attributed*
REFERENCE_WORDS = {'by', 'on', 'after', 'of', 'from', 'a', 'an'}


# Build a quick set of last-name keys we know about
with open(DICT_PATH) as f:
    composer_dict = json.load(f)
known_last_names = {entry['key'] for entry in composer_dict}
print(f"Loaded dictionary: {len(known_last_names)} known composer last names.\n")


# Back up
if Path(BACKUP_PATH).exists():
    print(f"Note: {BACKUP_PATH} already exists; overwriting.")
shutil.copy(DB_PATH, BACKUP_PATH)
print(f"Backed up {DB_PATH} → {BACKUP_PATH}\n")


conn = sqlite3.connect(DB_PATH)
conn.row_factory = sqlite3.Row

rows = conn.execute(
    "SELECT id, title, composer FROM pieces WHERE chosen_by='Michael'"
).fetchall()

changed = 0
skipped_no_match = 0
skipped_reference = 0

for row in rows:
    rid = row['id']
    title = row['title'] or ''
    composer = (row['composer'] or '').strip()

    if not composer or not title:
        skipped_no_match += 1
        continue

    bare_composer = strip_arr_prefix(composer)
    composer_ln = last_name_of(bare_composer)
    if not composer_ln or composer_ln not in known_last_names:
        skipped_no_match += 1
        continue

    # Look at the first few words of the title. If the composer's last name is in
    # the first 3-4 words, AND no reference word precedes it, strip up to and
    # including that word.
    words = title.split()
    if len(words) < 2:
        skipped_no_match += 1
        continue

    # Find where the composer's last name appears
    composer_word_idx = -1
    for i, w in enumerate(words[:5]):  # only check first 5 words
        word_norm = strip_accents(w.rstrip(',.;:')).lower()
        if word_norm == composer_ln:
            composer_word_idx = i
            break

    if composer_word_idx < 0:
        skipped_no_match += 1
        continue

    # Check whether a reference word precedes the composer name
    has_reference = False
    for j in range(composer_word_idx):
        if words[j].rstrip(',.;:').lower() in REFERENCE_WORDS:
            has_reference = True
            break

    if has_reference:
        skipped_reference += 1
        continue

    # Strip up to and including the composer's last name
    new_words = words[composer_word_idx + 1:]
    new_title = ' '.join(new_words).lstrip(' ,;:-–—').strip()

    if not new_title or new_title == title:
        skipped_no_match += 1
        continue

    conn.execute("UPDATE pieces SET title=? WHERE id=?", (new_title, rid))
    changed += 1

conn.commit()
conn.close()

print(f"Done.")
print(f"  {changed:4} titles had a leading composer name trimmed off")
print(f"  {skipped_reference:4} rows skipped because the composer was referenced (by, on, after, etc.)")
print(f"  {skipped_no_match:4} rows untouched\n")
print(f"To restore: cp {BACKUP_PATH} {DB_PATH}")