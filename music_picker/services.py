import unicodedata
from datetime import date as date_class
import re

from .calendar_utils import format_last_played, to_sortable_date
from .constants import MONTHS_REV, SLOTS
from .db import get_db


def is_library(r):
    try:
        return bool(r['library_only'])
    except (KeyError, IndexError):
        return False

def _fold(s):
    """Lowercase + strip diacritics so 'Faure' matches 'Fauré'."""
    if not s:
        return ''
    decomposed = unicodedata.normalize('NFKD', s)
    return ''.join(c for c in decomposed if not unicodedata.combining(c)).lower()

def normalize_search_text(value):
    """Normalize text for forgiving search.

    Examples:
    - Angels' Carol -> angels carol
    - Come, O Long-expected Jesus -> come o long expected jesus
    - Noël -> noel
    """
    value = value or ""
    value = unicodedata.normalize("NFKD", str(value))
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    value = value.lower()
    value = value.replace("’", "'").replace("‘", "'")
    value = value.replace("“", '"').replace("”", '"')
    value = re.sub(r"[^a-z0-9]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def normalized_contains(haystack, needle):
    needle_norm = normalize_search_text(needle)
    if not needle_norm:
        return True
    return needle_norm in normalize_search_text(haystack)


def matches_search(row, search_q):
    """Forgiving search across common repertoire fields."""
    search_q = search_q or ""
    if not search_q.strip():
        return True

    fields = [
        row.get("title", ""),
        row.get("composer", ""),
        row.get("composer_dates", ""),
        row.get("occasion", ""),
        row.get("season", ""),
        row.get("source_file", ""),
        row.get("notes", ""),
        row.get("hymn_no", ""),
    ]

    return normalized_contains(" ".join(str(f or "") for f in fields), search_q)


def get_sunday_summary(d):
    date_str = f'{MONTHS_REV[d.month]} {d.day:02d}'
    rows = get_db().execute(
        "SELECT * FROM pieces WHERE calendar_year=? AND date=?",
        (d.year, date_str),
    ).fetchall()
    pieces = {s: '' for s in SLOTS}
    occasion = ''
    for r in rows:
        if is_library(r):
            continue
        if r['slot'] in SLOTS and r['chosen_by'] == 'Michael':
            pieces[r['slot']] = r['title']
        if r['occasion'] and not occasion:
            occasion = r['occasion']
    return {'pieces': pieces, 'occasion': occasion}


def get_repertoire_results(search_q='', season='', slot='', limit=None):
    """Shared repertoire/library search used by index and planning sidebar.

    New model:
    - personal_library is the canonical list of personal/instrumental repertoire.
    - pieces is dated planning/history usage.
    - Unused repertoire is not in a separate silo; it is simply library repertoire
      with no usage rows yet.
    """
    db = get_db()
    search_q = (search_q or '').strip()
    season = season or ''
    slot = slot or ''

    # 1. Start from canonical personal library.
    library_rows = db.execute("""
        SELECT *
        FROM personal_library
        WHERE active=1
        ORDER BY title COLLATE NOCASE
    """).fetchall()

    library_rows = [dict(r) for r in library_rows]

    # 2. Apply broad library filters.
    if season:
        library_rows = [r for r in library_rows if (r.get('season') or '') == season]

    if search_q:
        def lib_matches(r):
            haystack = " ".join([
                r.get('title') or '',
                r.get('composer') or '',
                r.get('composer_dates') or '',
                r.get('season') or '',
                r.get('source_file') or '',
                r.get('notes') or '',
            ])
            return normalized_contains(haystack, search_q)

        library_rows = [r for r in library_rows if lib_matches(r)]

    library_ids = [r['id'] for r in library_rows]

    if not library_ids:
        return [], 0

    # 3. Pull all linked personal usage/history rows for these library items.
    placeholders = ",".join(["?"] * len(library_ids))
    usage_rows = db.execute(f"""
        SELECT *
        FROM pieces
        WHERE chosen_by='Michael'
          AND source_type='personal'
          AND source_id IN ({placeholders})
          AND (library_only=0 OR library_only IS NULL)
    """, library_ids).fetchall()

    usage_rows = [r for r in usage_rows if to_sortable_date(r) != (0, 0, 0)]

    if slot:
        usage_rows = [r for r in usage_rows if r['slot'] == slot]
        used_ids = {r['source_id'] for r in usage_rows}
        library_rows = [r for r in library_rows if r['id'] in used_ids]

    today = date_class.today()
    today_tuple = (today.year, today.month, today.day)

    usage_by_id = {}
    for r in usage_rows:
        source_id = r['source_id']
        if source_id not in usage_by_id:
            usage_by_id[source_id] = []
        usage_by_id[source_id].append(r)

    out = []

    for lib in library_rows:
        lib_id = lib['id']
        usages = usage_by_id.get(lib_id, [])

        past_dates = []
        future_dates = []

        for u in usages:
            d = to_sortable_date(u)
            if d >= today_tuple:
                future_dates.append(d)
            else:
                past_dates.append(d)

        last_past = max(past_dates) if past_dates else (0, 0, 0)
        next_future = min(future_dates) if future_dates else None

        never_used = not past_dates and not future_dates
        scheduled_only = (not past_dates) and bool(next_future)

        out.append({
            'id': lib_id,
            'title': lib.get('title') or '',
            'composer': lib.get('composer') or '',
            'composer_dates': lib.get('composer_dates') or '',
            'last_played': last_past,
            'last_played_str': format_last_played(last_past) if past_dates else '',
            'times': len(past_dates),
            'next_scheduled': next_future,
            'next_scheduled_str': format_last_played(next_future) if next_future else '',
            # Keep template compatibility:
            # library=True now means "never used yet," not "separate library-only silo."
            'library': never_used,
            'scheduled_only': scheduled_only,
            'source_label': lib.get('source_file') or '',
        })

    # 4. Sort:
    # - used repertoire first, oldest last-played first
    # - scheduled-only next
    # - never-used at bottom alphabetically
    def sort_key(r):
        if r['last_played'] != (0, 0, 0):
            return (0, r['last_played'], r['title'].lower())
        if r['scheduled_only']:
            return (1, r['next_scheduled'] or (9999, 12, 31), r['title'].lower())
        return (2, r['title'].lower())

    out.sort(key=sort_key)

    total = len(out)
    if limit is not None and total > limit:
        out = out[:limit]

    return out, total


def get_past_pieces_for_season(season, search_q='', limit=None, slot=''):
    """Backward-compatible wrapper for the plan sidebar."""
    return get_repertoire_results(
        search_q=search_q,
        season=season or '',
        slot=slot or '',
        limit=limit,
    )
