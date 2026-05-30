"""
Delete all entries whose title starts with "(Leo):" — these came from
some non-music notation in the source documents.
Backs up the database before any changes.
"""

import sqlite3
import shutil
from pathlib import Pa
from datetime import datetime

DB_PATH = 'repertoire.db'
BACKUP_PATH = f'repertoire.db.backup_leo_{datetime.now().strftime("%Y%m%d_%H%M%S")}'

# Back up first
shutil.copy(DB_PATH, BACKUP_PATH)
print(f"Backed up {DB_PATH} → {BACKUP_PATH}")

conn = sqlite3.connect(DB_PATH)
conn.row_factory = sqlite3.Row

# Show what will be deleted, before deleting
to_delete = conn.execute(
    "SELECT id, title, date, calendar_year FROM pieces WHERE title LIKE '(Leo):%'"
).fetchall()

print(f"\nFound {len(to_delete)} rows starting with '(Leo):':")
for r in to_delete:
    print(f"  {r['calendar_year']} {r['date']}: {r['title'][:70]}")

if not to_delete:
    print("\nNothing to delete.")
    conn.close()
else:
    confirm = input(f"\nDelete these {len(to_delete)} rows? [y/N] ").strip().lower()
    if confirm == 'y':
        conn.execute("DELETE FROM pieces WHERE title LIKE '(Leo):%'")
        conn.commit()
        print(f"Deleted {len(to_delete)} rows.")
    else:
        print("Aborted — no changes made.")
    conn.close()

print(f"\nTo restore: cp {BACKUP_PATH} {DB_PATH}")