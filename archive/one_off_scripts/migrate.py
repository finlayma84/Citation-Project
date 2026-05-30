import json
import sqlite3

with open('repertoire.json') as f:
    store = json.load(f)

conn = sqlite3.connect('repertoire.db')
c = conn.cursor()

# Drop and recreate so this script is safe to re-run.
c.execute('DROP TABLE IF EXISTS pieces')
c.execute('''
    CREATE TABLE pieces (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        season TEXT,
        lectionary_year TEXT,
        calendar_year INTEGER,
        date TEXT,
        occasion TEXT,
        slot TEXT,
        performer TEXT,
        chosen_by TEXT,
        title TEXT,
        composer TEXT,
        composer_dates TEXT,
        hymn_no TEXT,
        flag TEXT,
        source_file TEXT,
        status TEXT DEFAULT 'played'
    )
''')

for r in store:
    c.execute('''
        INSERT INTO pieces
        (season, lectionary_year, calendar_year, date, occasion, slot, performer,
         chosen_by, title, composer, composer_dates, hymn_no, flag, source_file, status)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', (
        r.get('season'), r.get('lectionary_year'), r.get('calendar_year'),
        r.get('date'), r.get('occasion'), r.get('slot'), r.get('performer'),
        r.get('chosen_by'), r.get('title'), r.get('composer'),
        r.get('composer_dates'), r.get('hymn_no'), r.get('flag'),
        r.get('source_file'), 'played',
    ))

conn.commit()

# Sanity-check
count = c.execute('SELECT COUNT(*) FROM pieces').fetchone()[0]
print(f'Inserted {count} rows into repertoire.db')

conn.close()