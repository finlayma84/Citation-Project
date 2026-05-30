from datetime import date as date_class

from .calendar_utils import format_last_played, to_sortable_date
from .constants import MONTHS_REV, SLOTS
from .db import get_db


def is_library(r):
    try:
        return bool(r['library_only'])
    except (KeyError, IndexError):
        return False


def matches_search(row_dict, search_term):
    if not search_term:
        return True
    needle = search_term.lower()
    fields = [
        row_dict.get('title', '') or '',
        row_dict.get('composer', '') or '',
        row_dict.get('composer_dates', '') or '',
        row_dict.get('occasion', '') or '',
        row_dict.get('source_file', '') or '',
    ]
    return any(needle in (f or '').lower() for f in fields)


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


def get_past_pieces_for_season(season, search_q='', limit=None):
    """Return both played-history rows and library-only rows.

    Library entries are season-agnostic and sort first because they have
    never been played. Played entries respect the selected season filter.
    """
    library_rows = get_db().execute(
        "SELECT * FROM pieces WHERE chosen_by='Michael' AND library_only=1"
    ).fetchall()

    if season:
        played_raw = get_db().execute(
            "SELECT * FROM pieces WHERE season=? AND chosen_by='Michael' AND (library_only=0 OR library_only IS NULL)",
            (season,),
        ).fetchall()
    else:
        played_raw = get_db().execute(
            "SELECT * FROM pieces WHERE chosen_by='Michael' AND (library_only=0 OR library_only IS NULL)"
        ).fetchall()

    today = date_class.today()
    today_tuple = (today.year, today.month, today.day)
    played = [r for r in played_raw if to_sortable_date(r) < today_tuple]

    if search_q:
        played = [r for r in played if matches_search(dict(r), search_q)]
        library_rows = [r for r in library_rows if matches_search(dict(r), search_q)]

    seen = {}
    for r in played:
        if r['title'] not in seen:
            seen[r['title']] = {
                'row': r,
                'count': 0,
                'last': (0, 0, 0),
                'composer': r['composer'],
                'composer_dates': r['composer_dates'],
            }
        seen[r['title']]['count'] += 1
        d = to_sortable_date(r)
        if d > seen[r['title']]['last']:
            seen[r['title']]['last'] = d
            seen[r['title']]['composer'] = r['composer']
            seen[r['title']]['composer_dates'] = r['composer_dates']

    played_titles = set(seen.keys())
    out = []
    for r in library_rows:
        if r['title'] in played_titles:
            continue
        out.append({
            'title': r['title'],
            'composer': r['composer'] or '',
            'composer_dates': r['composer_dates'] or '',
            'last_played': (0, 0, 0),
            'last_played_str': '',
            'times': 0,
            'library': True,
        })

    played_out = [{
        'title': k,
        'composer': v['composer'] or '',
        'composer_dates': v['composer_dates'] or '',
        'last_played': v['last'],
        'last_played_str': format_last_played(v['last']),
        'times': v['count'],
        'library': False,
    } for k, v in seen.items()]
    played_out.sort(key=lambda r: r['last_played'])
    out.extend(played_out)

    total = len(out)
    if limit is not None and total > limit:
        out = out[:limit]
    return out, total
