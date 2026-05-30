"""Add the library_only flag to pieces."""
import sqlite3

conn = sqlite3.connect('repertoire.db')
c = conn.cursor()

# Add column if it doesn't exist
cols = [r[1] for r in c.execute("PRAGMA table_info(pieces)").fetchall()]
if 'library_only' not in cols:
    c.execute("ALTER TABLE pieces ADD COLUMN library_only INTEGER DEFAULT 0")
    print("Added library_only column")
else:
    print("library_only column already present")

conn.commit()
conn.close()
