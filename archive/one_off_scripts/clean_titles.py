"""
Pass 3: Strip composer name + dates from the trailing end of title fields,
where the composer field already correctly identifies the composer.
"""

import sqlite3
import shutil
import re
import unicodedata
from pathlib import Path

DB_PATH = 'repertoire.db'
BACKUP_PATH = 'repertoire.db.backup_pass3'


def strip_accents(s):
    return ''.join(c for c in unicodedata.normalize('NFD', s)
                   if unicodedata.category(c) != 'Mn')


def strip_arr_prefix(name):
    """Remove 'arr.' / 'Arr.' prefix; return just the name."""
    n = name.strip()
    for prefix in ('arr.', 'Arr.', 'arr ', 'Arr ', 'arranged by ', 'Arranged by '):
        if n.lower().startswith(prefix.lower()):
            return n[len(prefix):].strip()
    return n


# Back up first
if Path(BACKUP_PATH).exists():
    print(f"Note: {BACKUP_PATH} already exists; overwriting.")
shutil.copy(DB_PATH, BACKUP_PATH)
print(f"Backed up {DB_PATH} → {BACKUP_PATH}\n")


conn = sqlite3.connect(DB_PATH)
conn.row_factory = sqlite3.Row

rows = conn.execute(
    "SELECT id, title, composer, composer_dates FROM pieces WHERE chosen_by='Michael'"
).fetchall()

changed = 0
skipped_no_composer = 0
skipped_not_found = 0

for row in rows:
    rid = row['id']
    title = row['title'] or ''
    composer = (row['composer'] or '').strip()
    dates = (row['composer_dates'] or '').strip()

    if not composer:
        skipped_no_composer += 1
        continue

    # Get the bare composer name (without "arr." prefix) — that's what we expect to find in the title
    bare_composer = strip_arr_prefix(composer)
    if not bare_composer:
        skipped_no_composer += 1
        continue

    # Build a search pattern: composer name (accents-insensitive), optionally followed
    # by the dates in parens or bare.
    # We search case-insensitively, accent-insensitively, and only match if the composer
    # name appears toward the END of the title (last 60% of the string).

    title_norm = strip_accents(title).lower()
    composer_norm = strip_accents(bare_composer).lower()

    idx = title_norm.find(composer_norm)
    if idx < 0:
        skipped_not_found += 1
        continue

    # Only strip if the composer appears in the back half of the title — otherwise
    # the title might legitimately START with the composer's name (e.g., "Bach Prelude...")
    if idx < len(title_norm) * 0.4:
        skipped_not_found += 1
        continue

    # Cut the title at the start of the composer name and clean up trailing punctuation/whitespace
    new_title = title[:idx].rstrip(' ,;|-–—').strip()

    if not new_title or new_title == title:
        skipped_not_found += 1
        continue

    conn.execute("UPDATE pieces SET title=? WHERE id=?", (new_title, rid))
    changed += 1

conn.commit()
conn.close()

print(f"Done.")
print(f"  {changed:4} titles had composer/dates trimmed off the end")
print(f"  {skipped_no_composer:4} rows had no composer field to match against")
print(f"  {skipped_not_found:4} rows had a composer field but couldn't find it in the title")
print(f"\nTo restore: cp {BACKUP_PATH} {DB_PATH}")