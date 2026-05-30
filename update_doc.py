"""
Update an existing Music doc in place: replace slot lines with current database values.
Identifies slot lines by their label prefix (PRELUDE:, MIN MUSIC:, etc., or [PRELUDE: ...]).
Walks the doc paragraph-by-paragraph, using date headers to know which Sunday we're in.
"""

import re
import sqlite3
from datetime import date as date_class, datetime
from docx import Document
from docx.shared import Pt
from docx.shared import RGBColor

from generate_doc import (
    DB_PATH, MONTHS, MONTHS_REV, SLOTS, SLOT_LABEL, SLOT_ALIASES,
    DEFAULT_FONT, BODY_SIZE, get_pieces_for_date, slot_line_text,
    clear_paragraph_runs, write_slot_paragraph,
)

# Detect Michael-owned slot lines/placeholders.
# Supports new placeholders like {PRELUDE}, new labels like MUSIC MINISTRY/OFFERTORY,
# and older labels like MIN MUSIC/OFFERING so existing docs keep syncing.
ALL_SLOT_LABELS = sorted(
    {label for labels in SLOT_ALIASES.values() for label in labels},
    key=len,
    reverse=True,
)
SLOT_LINE_RE = re.compile(
    r'^(?:\{)?(' + '|'.join(re.escape(label) for label in ALL_SLOT_LABELS) + r')(?:\})?(?:\s*:|$)',
    re.I
)

# Detect a date header: "MAY 31 Trinity Sunday", "JUN 07 Second Sunday w/Communion | ..."
DATE_HEADER_RE = re.compile(r'^([A-Z]{3})\s+(\d{1,2})\b')


def slot_from_label(label_text):
    """Map a display label or placeholder text back to our canonical DB slot name."""
    up = label_text.upper().strip().strip('{}')
    for slot, labels in SLOT_ALIASES.items():
        if up in labels:
            return slot
    return None


def rewrite_slot_paragraph(paragraph, slot, piece):
    """Replace a music-slot paragraph using the same formatting as newly generated docs.

    This avoids a subtle bug where a filled piece inherited the gray/italic
    placeholder formatting after syncing.
    """
    clear_paragraph_runs(paragraph)
    write_slot_paragraph(paragraph, slot, piece)


def update_doc_for_season(season, year):
    """Update the doc on disk for the given season+year. Returns (success, message)."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        "SELECT doc_path FROM doc_paths WHERE season_year=?",
        (f'{season}-{year}',)
    ).fetchone()
    if not row:
        conn.close()
        return False, f"No doc generated yet for {season} {year}"

    from pathlib import Path
    path = Path(row['doc_path'])
    if not path.exists():
        conn.close()
        return False, f"Doc no longer exists at {path}"

    doc = Document(str(path))

    current_date = None     # the date we're currently inside (date_class)
    current_year = year

    for paragraph in doc.paragraphs:
        text = paragraph.text.strip()
        if not text:
            continue

        # Is this a date header?
        m = DATE_HEADER_RE.match(text)
        if m:
            mon_str = m.group(1)
            day = int(m.group(2))
            if mon_str in MONTHS:
                try:
                    current_date = date_class(current_year, MONTHS[mon_str], day)
                except ValueError:
                    current_date = None
            continue

        # Is this a slot line, and do we know which Sunday we're in?
        if current_date is None:
            continue
        m = SLOT_LINE_RE.match(text)
        if not m:
            continue
        slot = slot_from_label(m.group(1))
        if not slot:
            continue

        # Look up what the database says for this Sunday + slot
        data = get_pieces_for_date(conn, current_date)
        piece = data['pieces'][slot]
        new_text = slot_line_text(slot, piece)
        if new_text != text:
            rewrite_slot_paragraph(paragraph, slot, piece)

    doc.save(str(path))

    # Record sync time
    conn.execute(
        "UPDATE doc_paths SET last_synced_at=? WHERE season_year=?",
        (datetime.now().isoformat(timespec='seconds'), f'{season}-{year}')
    )
    conn.commit()
    conn.close()

    return True, str(path)