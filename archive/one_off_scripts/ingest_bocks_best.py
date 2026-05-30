"""
Ingest Bock's Best (Fred Bock Music Company, 1980) into the library.
Each entry becomes a library_only row in pieces — no date, no slot,
just title + composer + source. They'll appear in the planning sidebar
as available options.
"""
import sqlite3
import csv
from datetime import datetime
import shutil

DB_PATH = 'repertoire.db'
BACKUP_PATH = f'repertoire.db.backup_bocks_{datetime.now().strftime("%Y%m%d_%H%M%S")}'
SOURCE = "Bock's Best (Fred Bock Music, 1980)"

shutil.copy(DB_PATH, BACKUP_PATH)
print(f"Backed up {DB_PATH} → {BACKUP_PATH}")

conn = sqlite3.connect(DB_PATH)
c = conn.cursor()

# Refuse to double-ingest
already = c.execute(
    "SELECT COUNT(*) FROM pieces WHERE source_file=? AND library_only=1",
    (SOURCE,)
).fetchone()[0]
if already:
    print(f"Already ingested ({already} rows from this source). Aborting.")
    conn.close()
    raise SystemExit

n = 0
with open('bocks_best.csv') as f:
    reader = csv.DictReader(f)
    for row in reader:
        title = row['title'].strip()
        composer = row['composer'].strip()
        notation = f"#{row['page']}"  # store page number in hymn_no for now
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
        n += 1

conn.commit()
conn.close()
print(f"Ingested {n} library entries from {SOURCE}")
