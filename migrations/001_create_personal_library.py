import re
import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "repertoire.db"


def clean(value):
    return (value or "").strip()


def normalize_key(value):
    value = clean(value).lower()
    value = re.sub(r"\s+", " ", value)
    value = value.replace("’", "'").replace("“", '"').replace("”", '"')
    return value


def add_column_if_missing(cur, table, column, definition):
    cols = [row[1] for row in cur.execute(f"PRAGMA table_info({table})").fetchall()]
    if column not in cols:
        cur.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
        print(f"Added {table}.{column}")


def table_exists(cur, table):
    row = cur.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
        (table,),
    ).fetchone()
    return row is not None


con = sqlite3.connect(DB_PATH)
con.row_factory = sqlite3.Row
cur = con.cursor()

# Ensure source tracking exists on usage/history rows.
add_column_if_missing(cur, "pieces", "source_type", "TEXT")
add_column_if_missing(cur, "pieces", "source_id", "INTEGER")

# Create canonical personal library table.
cur.execute("""
CREATE TABLE IF NOT EXISTS personal_library (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    composer TEXT,
    composer_dates TEXT,
    season TEXT,
    source_file TEXT,
    notes TEXT,
    active INTEGER DEFAULT 1
)
""")

# Pull all Michael rows that look like personal/instrumental repertoire.
# We include both dated usages and old library_only rows.
rows = cur.execute("""
    SELECT *
    FROM pieces
    WHERE chosen_by='Michael'
      AND title IS NOT NULL
      AND title != ''
      AND (slot IS NULL OR slot != 'Hymn')
""").fetchall()

library_by_key = {}
inserted = 0
linked = 0

# First pass: create one canonical item per normalized title+composer.
for r in rows:
    title = clean(r["title"])
    composer = clean(r["composer"])
    if not title:
        continue

    key = (normalize_key(title), normalize_key(composer))

    if key in library_by_key:
        continue

    # Prefer fuller composer dates/source/season from the first row we encounter.
    composer_dates = clean(r["composer_dates"])
    season = clean(r["season"])
    source_file = clean(r["source_file"]) if "source_file" in r.keys() else ""

    cur.execute("""
        INSERT INTO personal_library (
            title, composer, composer_dates, season, source_file, notes, active
        )
        VALUES (?, ?, ?, ?, ?, '', 1)
    """, (
        title,
        composer,
        composer_dates,
        season,
        source_file,
    ))

    library_id = cur.lastrowid
    library_by_key[key] = library_id
    inserted += 1

# Second pass: improve incomplete canonical records where later rows have better metadata.
for r in rows:
    title = clean(r["title"])
    composer = clean(r["composer"])
    if not title:
        continue

    key = (normalize_key(title), normalize_key(composer))
    library_id = library_by_key.get(key)
    if not library_id:
        continue

    lib = cur.execute("SELECT * FROM personal_library WHERE id=?", (library_id,)).fetchone()

    improved_dates = clean(lib["composer_dates"]) or clean(r["composer_dates"])
    improved_season = clean(lib["season"]) or clean(r["season"])
    improved_source = clean(lib["source_file"]) or (clean(r["source_file"]) if "source_file" in r.keys() else "")

    cur.execute("""
        UPDATE personal_library
        SET composer_dates=?,
            season=?,
            source_file=?
        WHERE id=?
    """, (
        improved_dates,
        improved_season,
        improved_source,
        library_id,
    ))

# Third pass: link existing dated/history rows and old library_only rows to canonical library items.
for r in rows:
    title = clean(r["title"])
    composer = clean(r["composer"])
    if not title:
        continue

    key = (normalize_key(title), normalize_key(composer))
    library_id = library_by_key.get(key)
    if not library_id:
        continue

    cur.execute("""
        UPDATE pieces
        SET source_type='personal',
            source_id=?
        WHERE id=?
    """, (library_id, r["id"]))
    linked += 1

con.commit()

print()
print("Migration complete.")
print(f"Personal library items inserted: {inserted}")
print(f"Pieces/history rows linked: {linked}")

print()
print("Sample personal_library rows:")
for row in cur.execute("""
    SELECT id, title, composer, composer_dates, season
    FROM personal_library
    ORDER BY title COLLATE NOCASE
    LIMIT 20
"""):
    print(dict(row))

con.close()
