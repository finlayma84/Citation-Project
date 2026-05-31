import unicodedata
from datetime import date as date_class

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
def matches_search(row_dict, search_term):
    if not search_term:
        return True
    needle = _fold(search_term)
    fields = [
        row_dict.get('title', '') or '',
        row_dict.get('composer', '') or '',
        row_dict.get('composer_dates', '') or '',
        row_dict.get('occasion', '') or '',
        row_dict.get('source_file', '') or '',
    ]
    return any(needle in _fold(f) for f in fields)


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
    """Shared repertoire/history search used by index and planning sidebar.

    Rules:
    - Search title/composer/dates/occasion/source across the same data everywhere.
    - Dated/planned rows include past and future scheduled pieces.
    - Season and slot are browsing filters for dated/planned rows.
    - Library-only rows appear at the bottom alphabetically when no season/slot
      filter is active, or when a search matches them and no slot filter is active.
    - Library-only rows are hidden by slot filter because they have no usage slot.
    """
    db = get_db()

    library_rows = db.execute(
        "SELECT * FROM pieces WHERE chosen_by='Michael' AND library_only=1"
    ).fetchall()

    dated_rows = db.execute(
        "SELECT * FROM pieces WHERE chosen_by='Michael' AND (library_only=0 OR library_only IS NULL)"
    ).fetchall()

    dated_rows = [r for r in dated_rows if to_sortable_date(r) != (0, 0, 0)]

    if season:
        dated_rows = [r for r in dated_rows if r['season'] == season]

    if slot:
        dated_rows = [r for r in dated_rows if r['slot'] == slot]
        # Library-only rows have no real usage slot yet.
        library_rows = []

    if search_q:
        dated_rows = [r for r in dated_rows if matches_search(dict(r), search_q)]
        library_rows = [r for r in library_rows if matches_search(dict(r), search_q)]
    elif season:
        # When browsing a specific season, don't flood the list with seasonless library rows.
        library_rows = []

    today = date_class.today()
    today_tuple = (today.year, today.month, today.day)

    seen = {}

    for r in dated_rows:
        title = r['title'] or ''
        d = to_sortable_date(r)
        is_future = d >= today_tuple

        if title not in seen:
            seen[title] = {
                'row': r,
                'count': 0,
                'last': (0, 0, 0),
                'next_future': None,
                'composer': r['composer'],
                'composer_dates': r['composer_dates'],
            }

        entry = seen[title]
        entry['count'] += 1

        if d > entry['last']:
            entry['last'] = d
            entry['row'] = r
            entry['composer'] = r['composer']
            entry['composer_dates'] = r['composer_dates']

        if is_future:
            if entry['next_future'] is None or d < entry['next_future']:
                entry['next_future'] = d

    dated_titles = set(seen.keys())

    dated_out = []
    for title, v in seen.items():
        next_future = v['next_future']
        scheduled_only = next_future is not None and v['last'] >= today_tuple

        dated_out.append({
            'title': title,
            'composer': v['composer'] or '',
            'composer_dates': v['composer_dates'] or '',
            'last_played': v['last'],
            'last_played_str': format_last_played(v['last']),
            'next_scheduled': next_future,
            'next_scheduled_str': format_last_played(next_future) if next_future else '',
            'times': v['count'],
            'library': False,
            'scheduled_only': scheduled_only,
            'source_file': '',
            'hymn_no': '',
            'source_label': '',
        })

    # Dated/planned repertoire first: oldest/longest-since-used first.
    dated_out.sort(key=lambda r: r['last_played'])

    library_out = []
    for r in library_rows:
        if r['title'] in dated_titles:
            continue

        source_file = r['source_file'] or ''
        hymn_no = r['hymn_no'] or ''

        if source_file and hymn_no:
            source_label = f"{source_file} · {hymn_no}"
        elif source_file:
            source_label = source_file
        elif hymn_no:
            source_label = hymn_no
        else:
            source_label = ''

        library_out.append({
            'title': r['title'] or '',
            'composer': r['composer'] or '',
            'composer_dates': r['composer_dates'] or '',
            'last_played': (9999, 12, 31),
            'last_played_str': '',
            'next_scheduled': None,
            'next_scheduled_str': '',
            'times': 0,
            'library': True,
            'scheduled_only': False,
            'source_file': source_file,
            'hymn_no': hymn_no,
            'source_label': source_label,
        })

    # Never-played library repertoire goes at the bottom, alphabetized.
    library_out.sort(key=lambda r: (
        (r['title'] or '').lower(),
        (r['source_file'] or '').lower(),
        (r['hymn_no'] or '').lower(),
    ))

    out = dated_out + library_out

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
