"""One-time migration: add the doc_paths table for tracking generated docs."""
import sqlite3

conn = sqlite3.connect('repertoire.db')
c = conn.cursor()

c.execute('''
    CREATE TABLE IF NOT EXISTS doc_paths (
        season_year TEXT PRIMARY KEY,
        doc_path TEXT NOT NULL,
        generated_at TEXT NOT NULL,
        last_synced_at TEXT
    )
''')
conn.commit()
conn.close()
print("doc_paths table ready")