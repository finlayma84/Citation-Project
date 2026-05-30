from calendar import monthrange
from datetime import date as date_class, timedelta
from dateutil.easter import easter

from .constants import MONTHS, MONTHS_REV


def to_sortable_date(r):
    year = r['calendar_year'] or 0
    mon_str, _, day_str = (r['date'] or '').partition(' ')
    return (year, MONTHS.get(mon_str, 0), int(day_str) if day_str.isdigit() else 0)


def format_last_played(t):
    year, month, _ = t
    if not year:
        return ''
    return f"{['','Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'][month]} {year}"


def iso_to_db_parts(iso):
    y, m, d = iso.split('-')
    return f'{MONTHS_REV[int(m)]} {int(d):02d}', int(y)


def sundays_in_month(year, month):
    _, last_day = monthrange(year, month)
    out = []
    for day in range(1, last_day + 1):
        d = date_class(year, month, day)
        if d.weekday() == 6:
            out.append(d)
    return out


def prev_month(year, month):
    if month == 1:
        return year - 1, 12
    return year, month - 1


def next_month(year, month):
    if month == 12:
        return year + 1, 1
    return year, month + 1


def season_for_date(d):
    year = d.year
    easter_sunday = easter(year)
    ash_wed = easter_sunday - timedelta(days=46)
    pentecost = easter_sunday + timedelta(days=49)
    jan6 = date_class(year, 1, 6)
    j_wd = jan6.weekday()
    if j_wd == 6:
        epiphany_sunday = jan6
    elif j_wd < 3:
        epiphany_sunday = jan6 - timedelta(days=j_wd + 1)
    else:
        epiphany_sunday = jan6 + timedelta(days=6 - j_wd)
    christmas = date_class(year, 12, 25)
    c_wd = christmas.weekday()
    days_back = (c_wd + 1) % 7
    if days_back == 0:
        days_back = 7
    sunday_before_christmas = christmas - timedelta(days=days_back)
    advent_start = sunday_before_christmas - timedelta(days=21)
    if d >= advent_start or d < epiphany_sunday:
        return 'Advent/Christmas'
    if d < ash_wed:
        return 'Epiphany'
    if d < easter_sunday:
        return 'Lent'
    # Eastertide runs through Pentecost Sunday; the Season after Pentecost begins on Trinity Sunday.
    if d <= pentecost:
        return 'Easter'
    return 'Pentecost'
