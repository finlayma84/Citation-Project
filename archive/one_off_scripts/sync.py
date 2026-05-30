"""
Walks the FCUCC Bulletins Dropbox folder, finds every 'Music *.docx' file,
parses it, and rebuilds the SQLite database from scratch.

Run manually from the terminal:  python sync.py
"""

import os
import re
import sqlite3
import hashlib
from pathlib import Path
from docx import Document

# ---- CONFIG ---------------------------------------------------------------
DROPBOX_ROOT = Path.home() / 'Dropbox' / 'FCUCC Bulletins'
DB_PATH = 'repertoire.db'

# ---- PARSER (same logic as before, packaged for reuse) --------------------
LETTER = {1: 'A', 2: 'B', 0: 'C'}
MONTHS = dict(JAN=1, FEB=2, MAR=3, APR=4, MAY=5, JUN=6, JUL=7,
              AUG=8, SEP=9, OCT=10, NOV=11, DEC=12)
SEASON_KEYS = [('advent', 'Advent/Christmas'), ('xmas', 'Advent/Christmas'),
               ('epiphany', 'Epiphany'), ('lent', 'Lent'),
               ('easter', 'Easter'), ('pent', 'Pentecost')]
MY_SLOTS = {'Prelude', 'Min Music', 'Offering', 'Postlude'}

date_re  = re.compile(r'^(?:Sunday,?\s+)?([A-Z][a-zA-Z]{2})\.?\s+(\d{1,2})\s*:?\s*(.*)$', re.I) 
label_re = re.compile(
    r'^(PRELUDES?|POSTLUDE|OFFERING|OFFERTORY|MIN\.? ?MUSIC|MINISTRY (?:OF )?MUSIC'
    r'|CHORAL ANTHEM|ANTHEM(?:/SOLO)?|SOLO|SPECIAL MUSIC|GLORIA PATRI'
    r'|FESTIVAL DOXOLOGY|DOXOLOGY|PRAYER OF ILLUMINATION|ILLUMINATION'
    r'|CONFESSION RESPONSE|RESPONSE|INTROIT)\b\s*:?\s*(.*)$', re.I)
cal_year_re = re.compile(r'(20\d{2})')

SLOT_CANON = {'prelude': 'Prelude', 'preludes': 'Prelude', 'postlude': 'Postlude',
              'offering': 'Offering', 'offertory': 'Offering'}

def canon_slot(label):
    l = label.lower().replace('.', '').strip()
    if l in SLOT_CANON:
        return SLOT_CANON[l]
    if l in ('min music', 'ministry music', 'ministry of music', 'anthem',
             'anthem/solo', 'choral anthem', 'solo', 'special music'):
        return 'Min Music'
    return label.title()

PERFORMER_HINTS = [
    (re.compile(r'\bchoir\b', re.I), 'Choir'),
    (re.compile(r'\bbell(s|choir)?\b|handbell', re.I), 'Bells'),
    (re.compile(r'string quartet|strings?\b|violin|viola|cello|bass\b', re.I), 'Instrumental'),
    (re.compile(r'\b(flute|oboe|clarinet|trumpet|horn|sax|guitar|harp|organ)\b', re.I), 'Instrumental'),
    (re.compile(r'\bsoloist|vocal solo|soprano|alto|tenor|baritone\b', re.I), 'Vocal solo'),
]

def derive_performer(label_raw, piece_text):
    default = 'Choir' if label_raw.strip().lower() == 'choral anthem' else 'Unspecified'
    for pat, who in PERFORMER_HINTS:
        if pat.search(piece_text):
            return who
    return default

def clean(s):
    return s.replace('*', '').strip().strip(',').strip()

def extract_dates(piece):
    flag = 'malformed date parens' if re.search(r'\)\s*\d{4}', piece) else None
    m = re.search(r'\(?\s*(b\.\s*)?(\d{4})\s*[–-]?\s*(\d{4})?\s*\)?', piece)
    if not m:
        return '', flag
    d = (m.group(1) or '') + m.group(2) + (('–' + m.group(3)) if m.group(3) else '')
    return d.strip(), flag

def guess_composer(piece, dates):
    head = piece
    if '|' in head:
        head = head.split('|')[0]
    elif dates and '(' in head:
        head = head[:head.rfind('(')]
    elif dates:
        m = re.search(r'\b(b\.\s*)?\d{4}', head)
        if m:
            head = head[:m.start()]
    head = head.strip().rstrip(',').strip()
    if ' by ' in head:
        head = head.split(' by ')[-1]
    if ',' in head:
        head = head.split(',')[-1]
    return head.strip()

def chosen_by(slot):
    if slot in MY_SLOTS:
        return 'Michael'
    if slot == 'Hymn':
        return 'Pastor'
    return 'Service music'

def parse_file(path):
    """Extract text from a .docx and parse out musical entries."""
    try:
        doc = Document(path)
    except Exception as e:
        print(f"  COULD NOT OPEN: {path.name}  ({e})")
        return None

    lines = [p.text for p in doc.paragraphs if p.text.strip()]
    name = path.name
    low = name.lower()
    season = next((lab for k, lab in SEASON_KEYS if k in low), 'UNKNOWN')

    header = lines[0] if lines else ''
    cy_match = cal_year_re.search(name) or cal_year_re.search(header)
    cy = int(cy_match.group(1)) if cy_match else None

    rows, current = [], None
    for raw in lines:
        line = raw.strip().replace('**', '').strip()
        if not line:
            continue
        d = date_re.match(line)
        if d and d.group(1).upper()[:3] in MONTHS:
            mon = d.group(1).upper()[:3]
            day, occ = d.group(2), d.group(3)
            current = {'date': f'{mon} {int(day):02d}', 'occasion': clean(occ)}
            continue
        if current is None:
            continue
        lab = label_re.match(line)
        if lab:
            slot = canon_slot(lab.group(1))
            piece = clean(lab.group(2))
            if not piece:
                continue
            dates, flag = extract_dates(piece)
            performer = derive_performer(lab.group(1), piece)
            rows.append({
                'slot': slot, 'performer': performer, 'title': piece,
                'composer': guess_composer(piece, dates),
                'composer_dates': dates, 'flag': flag or '',
                **current
            })
            continue
        if line.lstrip().startswith('*') and ':' not in line[:25]:
            title = clean(line)
            nm = re.search(r'(\d{1,3})\s*$', title)
            num = nm.group(1) if nm else ''
            if nm:
                title = clean(title[:nm.start()])
            if title:
                rows.append({
                    'slot': 'Hymn', 'performer': '', 'title': title,
                    'composer': '', 'composer_dates': '',
                    'hymn_no': num, 'flag': '',
                    **current
                })

    # derive lectionary year from calendar year if we have one
    lect = None
    if cy:
        lit_year = cy + 1 if season.startswith('Advent') else cy
        lect = LETTER[lit_year % 3]

    return {'season': season, 'lectionary_year': lect, 'calendar_year': cy,
            'source_file': name, 'rows': rows}


# ---- DISCOVERY ------------------------------------------------------------
def find_music_docs(root):
    """Walk the tree and yield Music *.docx files, ignoring lock files and conflicts."""
    for path in root.rglob('*.docx'):
        name = path.name
        if name.startswith('~$'):                       # Word lock files
            continue
        if 'conflicted copy' in name.lower() or "robin's changes" in name.lower():
            continue
        if not name.lower().startswith('music'):        # only Music * docs
            continue
        yield path


# ---- DATABASE BUILD -------------------------------------------------------
def rebuild_database():
    if not DROPBOX_ROOT.exists():
        print(f"ERROR: Dropbox folder not found at {DROPBOX_ROOT}")
        return

    paths = sorted(find_music_docs(DROPBOX_ROOT))
    print(f"Found {len(paths)} candidate Music *.docx files\n")

    # Dedup by content hash
    seen_hashes, unique_paths = {}, []
    for p in paths:
        h = hashlib.md5(p.read_bytes()).hexdigest()
        if h in seen_hashes:
            print(f"  skipping duplicate: {p.name}")
            continue
        seen_hashes[h] = p
        unique_paths.append(p)

    # Parse all
    print(f"\nParsing {len(unique_paths)} unique files...")
    all_rows = []
    for p in unique_paths:
        rec = parse_file(p)
        if rec is None:
            continue
        for r in rec['rows']:
            all_rows.append({
                'season': rec['season'],
                'lectionary_year': rec['lectionary_year'],
                'calendar_year': rec['calendar_year'],
                'date': r['date'], 'occasion': r['occasion'],
                'slot': r['slot'], 'performer': r.get('performer', ''),
                'chosen_by': chosen_by(r['slot']),
                'title': r['title'], 'composer': r.get('composer', ''),
                'composer_dates': r.get('composer_dates', ''),
                'hymn_no': r.get('hymn_no', ''), 'flag': r['flag'],
                'source_file': rec['source_file'],
                'status': 'played',
            })
        print(f"  {p.parent.name + '/' + p.name:60} -> {len(rec['rows']):3} entries")

    # Rebuild SQLite
    print(f"\nWriting {len(all_rows)} entries to {DB_PATH}...")
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('DROP TABLE IF EXISTS pieces')
    c.execute('''
        CREATE TABLE pieces (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            season TEXT, lectionary_year TEXT, calendar_year INTEGER,
            date TEXT, occasion TEXT, slot TEXT, performer TEXT,
            chosen_by TEXT, title TEXT, composer TEXT, composer_dates TEXT,
            hymn_no TEXT, flag TEXT, source_file TEXT,
            status TEXT DEFAULT 'played'
        )
    ''')
    for r in all_rows:
        c.execute('''
            INSERT INTO pieces (season, lectionary_year, calendar_year, date,
                occasion, slot, performer, chosen_by, title, composer,
                composer_dates, hymn_no, flag, source_file, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (r['season'], r['lectionary_year'], r['calendar_year'],
              r['date'], r['occasion'], r['slot'], r['performer'],
              r['chosen_by'], r['title'], r['composer'], r['composer_dates'],
              r['hymn_no'], r['flag'], r['source_file'], r['status']))
    conn.commit()

    total = c.execute('SELECT COUNT(*) FROM pieces').fetchone()[0]
    mine = c.execute("SELECT COUNT(*) FROM pieces WHERE chosen_by='Michael'").fetchone()[0]
    conn.close()
    print(f"\nDone. {total} total entries, {mine} of them yours.")


if __name__ == '__main__':
    rebuild_database()