"""
Ingest 33 Contemporary Hymns for Solo Piano, Volume 2
(Word Music, arranged by Carol Tornquist & Bill Wolaver) into the library.

Cross-references against the existing database — only pieces NOT already present
get ingested. 33 in the book, 3 already present, 30 new.

Composer field starts as "arr. Carol Tornquist or Bill Wolaver" since the TOC
doesn't attribute per piece — refine via the edit UI as pieces are programmed.
"""
import sqlite3
import csv
from datetime import datetime
import shutil
import re

DB_PATH = 'repertoire.db'
BACKUP_PATH = f'repertoire.db.backup_conthymns_{datetime.now().strftime("%Y%m%d_%H%M%S")}'
SOURCE = "33 Contemporary Hymns for Solo Piano, Vol. 2 (Word Music)"

shutil.copy(DB_PATH, BACKUP_PATH)
print(f"Backed up {DB_PATH} → {BACKUP_PATH}")

conn = sqlite3.connect(DB_PATH)
c = conn.cursor()

# Refuse double-ingest
already = c.execute(
    "SELECT COUNT(*) FROM pieces WHERE source_file=? AND library_only=1",
    (SOURCE,)
).fetchone()[0]
if already:
    print(f"Already ingested ({already} rows from this source). Aborting.")
    conn.close()
    raise SystemExit


def normalize(t):
    """Match existing-title normalization for de-duping."""
    if not t:
        return ''
    s = t.lower().strip()
    for prefix in ('the ', 'a ', 'an ', "'tis ", 'tis '):
        if s.startswith(prefix):
            s = s[len(prefix):]
            break
    s = re.sub(r'\([^)]*\)', '', s)
    s = re.sub(r'[^a-z0-9]', '', s)
    return s


# Build existing-titles set
existing = set()
for row in c.execute("""
    SELECT DISTINCT title FROM pieces
    WHERE chosen_by='Michael' AND title IS NOT NULL AND title != ''
"""):
    n = normalize(row[0])
    if n:
        existing.add(n)

# Ingest only what isn't already there
inserted = 0
skipped = 0
with open('contemporary_hymns_v2.csv') as f:
    reader = csv.DictReader(f)
    for row in reader:
        title = row['title'].strip()
        if normalize(title) in existing:
            print(f"  skip (already present): {title}")
            skipped += 1
            continue
        composer = row['composer'].strip()
        notation = f"#{row['page']}"
        c.execute('''
            INSERT INTO pieces
                (season, calendar_year, date, occasion, slot, performer,
                 chosen_by, title, composer, composer_dates, hymn_no,
                 source_file, status, library_only)
            VALUES
                ('', NULL, '', '', '', '',
                 'Michael', ?, ?, '', ?,
                 ?, 'library', 1)
        ''', (title, composer, notation, SOURCE))
        inserted += 1

conn.commit()
conn.close()
print(f"\nIngested {inserted} new library entries from {SOURCE}")
print(f"Skipped {skipped} (already in database)")
