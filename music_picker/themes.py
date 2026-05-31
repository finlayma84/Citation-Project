"""Sunday theme/context lookup for the planning page.

This module reads a small JSON reference file built from past church music
planning documents. The data is advisory: it gives a planning cue/theme to
display in the web app, but it does not affect the Word documents.
"""

from __future__ import annotations

import json
import re
from datetime import date as date_class, timedelta
from functools import lru_cache
from pathlib import Path


THEMES_PATH = Path(__file__).with_name("sunday_themes.json")


@lru_cache(maxsize=1)
def _theme_rows():
    if not THEMES_PATH.exists():
        return []

    try:
        payload = json.loads(THEMES_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []

    if isinstance(payload, dict):
        rows = payload.get("rows", [])
    elif isinstance(payload, list):
        rows = payload
    else:
        rows = []

    return [row for row in rows if isinstance(row, dict)]


def _advent_1(year: int) -> date_class:
    """Return the First Sunday of Advent for the calendar year."""
    christmas = date_class(year, 12, 25)
    days_back = (christmas.weekday() + 1) % 7 or 7
    fourth_advent = christmas - timedelta(days=days_back)
    return fourth_advent - timedelta(days=21)


def _lectionary_year(d: date_class) -> str:
    """Return the RCL year A/B/C for date d.

    The lectionary year begins with Advent 1 of the previous calendar year.
    Years beginning Advent 2022/2025/2028 are Year A.
    """
    cycle_year = d.year if d >= _advent_1(d.year) else d.year - 1
    return {0: "A", 1: "B", 2: "C"}[cycle_year % 3]


def _source_label(row: dict) -> str:
    source = row.get("source_docx") or row.get("source_zip") or ""
    if "/" in source:
        return source.rsplit("/", 1)[-1]
    return source


def _advent_default(liturgical_name: str | None) -> str:
    name = liturgical_name or ""
    defaults = {
        "First Sunday of Advent": "Hope",
        "Second Sunday of Advent": "Peace",
        "Third Sunday of Advent": "Joy",
        "Fourth Sunday of Advent": "Love",
        "First Sunday after Christmas": "Christmas / Incarnation",
        "Second Sunday after Christmas": "Christmas / Incarnation",
        "Epiphany of the Lord": "Magi / light to the nations",
    }
    return defaults.get(name, "")


def _proper_number(text: str | None) -> int | None:
    """Extract a Proper number from strings like 'Proper 12', 'Pr 12', 'PR 12'."""
    if not text:
        return None

    match = re.search(r"\b(?:proper|pr)\.?\s*(\d{1,2})\b", text, flags=re.I)
    if not match:
        return None

    try:
        return int(match.group(1))
    except ValueError:
        return None


def _is_junk_theme(text: str) -> bool:
    """Filter out logistics that are not real themes."""
    t = text.strip().lower()
    if not t:
        return True

    junk_bits = [
        "communion",
        "liturgist",
        "pastor away",
        "guest pastor",
        "guest preacher",
        "michael away",
        "mf away",
        "lay service",
        "father's day",
        "father’s day",
        "mother's day",
        "mother’s day",
        "annual meeting",
        "dedication pledges",
        "pastoral installation",
        "greg away",
        "rev.",
    ]

    return any(bit in t for bit in junk_bits)


def _clean_piece(text: str) -> str:
    text = (text or "").strip()
    text = text.strip(" |-/–—")
    text = re.sub(r"\s+", " ", text)
    return text


def _theme_from_note(note: str) -> str:
    """Try to extract the human planning label from a heading/planning note.

    Examples:
      'Pr 12 | Bread and Words | Jn 6:1-21' -> 'Bread and Words'
      'SEP 17: ... Mt 18:21-35 seventy times seven' -> 'seventy times seven'
      'World Communion Sunday | PR 22 (increase our faith)' -> 'increase our faith'
    """
    note = note or ""

    # Parenthetical labels are often the cleanest: "(increase our faith)".
    parens = re.findall(r"\(([^)]+)\)", note)
    for item in reversed(parens):
        item = _clean_piece(item)
        if item and not _is_junk_theme(item):
            return item

    # If a scripture citation is followed by a short phrase, use that.
    scripture_tail = re.search(
        r"\b(?:Mt|Matt|Matthew|Mk|Mark|Lk|Luke|Jn|John)\.?\s*"
        r"\d+[:\d,\-\s–]*\s+(.+)$",
        note,
        flags=re.I,
    )
    if scripture_tail:
        tail = _clean_piece(scripture_tail.group(1))
        if tail and not _is_junk_theme(tail):
            return tail

    # Otherwise inspect pipe-separated chunks from right to left.
    parts = [_clean_piece(p) for p in note.split("|")]
    for part in reversed(parts):
        if not part or _is_junk_theme(part):
            continue

        # Skip pure Sunday labels and Proper labels.
        low = part.lower()
        if "sunday" in low and len(part.split()) <= 6:
            continue
        if _proper_number(part) is not None and len(part.split()) <= 3:
            continue

        # Skip chunks that are only scripture citations.
        if re.search(r"\b(?:Mt|Matt|Matthew|Mk|Mark|Lk|Luke|Jn|John)\.?\s*\d+", part, flags=re.I):
            continue

        return part

    return ""


def _best_theme(row: dict) -> str:
    """Return the best display theme for a row."""
    explicit = _clean_piece(row.get("theme") or "")
    if explicit and not _is_junk_theme(explicit):
        return explicit

    note = row.get("planning_note") or row.get("heading_text") or ""
    return _theme_from_note(note)


def _make_result(row: dict, d: date_class, liturgical_name: str | None, season: str | None, match_type: str, theme: str) -> dict:
    return {
        "theme": theme,
        "planning_note": row.get("planning_note") or row.get("heading_text") or "",
        "heading_text": row.get("heading_text") or "",
        "season": row.get("season") or season or "",
        "lectionary_year": row.get("lectionary_year") or _lectionary_year(d),
        "source": _source_label(row),
        "source_full": row.get("source_docx") or row.get("source_zip") or "",
        "match_type": match_type,
    }


def get_theme_for_date(d: date_class, liturgical_name: str | None = None, season: str | None = None) -> dict | None:
    """Return Sunday planning context for a date.

    Lookup order:
    1. Exact archive date with usable theme.
    2. Same lectionary year + same Proper number.
    3. Exact archive date even if only planning_note is available.
    4. Advent/Christmas defaults.
    """
    iso = d.isoformat()
    rows = _theme_rows()
    lectionary_year = _lectionary_year(d)

    exact = [row for row in rows if row.get("iso_date") == iso]

    # 1. Exact date with usable theme.
    for row in sorted(exact, key=lambda r: 0 if _best_theme(r) else 1):
        theme = _best_theme(row)
        if theme:
            return _make_result(row, d, liturgical_name, season, "archive_exact", theme)

    # 2. Pentecost/Proper fallback: same lectionary year + same Proper number.
    # This lets Year A Proper 12 in 2026 reuse older/current Year A Proper 12 notes.
    target_proper = _proper_number(liturgical_name or "")
    if target_proper is None:
        for row in exact:
            target_proper = _proper_number(row.get("planning_note") or row.get("heading_text") or "")
            if target_proper is not None:
                break

    if target_proper is not None:
        proper_matches = []
        for row in rows:
            if row.get("lectionary_year") != lectionary_year:
                continue

            row_text = " ".join([
                row.get("planning_note") or "",
                row.get("heading_text") or "",
            ])
            if _proper_number(row_text) == target_proper:
                theme = _best_theme(row)
                if theme:
                    proper_matches.append((row, theme))

        if proper_matches:
            # Prefer current/future exact-ish sources and clean themes; otherwise first usable row.
            row, theme = proper_matches[-1]
            return _make_result(row, d, liturgical_name, season, "archive_proper", theme)

    # 3. Exact date, even with no extracted theme, so the planning note still appears.
    if exact:
        row = exact[0]
        fallback_theme = _advent_default(liturgical_name)
        return _make_result(row, d, liturgical_name, season, "archive_exact_note", fallback_theme)

    # 4. Stable defaults for Advent/Christmas/Epiphany.
    default_theme = _advent_default(liturgical_name)
    if default_theme:
        return {
            "theme": default_theme,
            "planning_note": liturgical_name or "",
            "heading_text": liturgical_name or "",
            "season": season or "",
            "lectionary_year": lectionary_year,
            "source": "default liturgical pattern",
            "source_full": "",
            "match_type": "default",
        }

    return None
