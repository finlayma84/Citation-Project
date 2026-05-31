from datetime import date as date_class, timedelta
from dateutil.easter import easter


def _advent_sunday_1(year):
    """The First Sunday of Advent: closest Sunday to Nov 30, on or after Nov 27."""
    christmas = date_class(year, 12, 25)
    days_back = (christmas.weekday() + 1) % 7 or 7
    fourth_advent = christmas - timedelta(days=days_back)
    return fourth_advent - timedelta(days=21)


def _epiphany_sunday(year):
    """The Sunday on or after January 6."""
    jan6 = date_class(year, 1, 6)
    wd = jan6.weekday()
    if wd == 6:
        return jan6
    return jan6 + timedelta(days=(6 - wd))


def _proper_number(d):
    """RCL Proper N for a date after Trinity Sunday.
    Proper N is assigned to the Sunday whose date falls in a fixed weekly window
    keyed off May 28. Proper 3 = May 24-28 window; numbering increments weekly."""
    # The RCL anchors Propers to fixed date ranges. The Sunday closest to
    # (but not before) a given Monday gets that week's Proper number.
    # Proper 4: May 29 - June 4
    # Proper 5: June 5 - June 11
    # ... and so on, each Proper covering a 7-day window starting on a Monday.
    proper_4_start = date_class(d.year, 5, 29)
    days = (d - proper_4_start).days
    if days < 0:
        return None
    return 4 + (days // 7)


def liturgical_name(d):
    """Return the proper liturgical name for the Sunday containing date d.

    Uses Revised Common Lectionary nomenclature (UCC, Methodist, Presbyterian, ELCA).
    Returns None if d is not a Sunday.
    """
    if d.weekday() != 6:
        return None

    year = d.year
    easter_sun = easter(year)
    ash_wed = easter_sun - timedelta(days=46)
    pentecost = easter_sun + timedelta(days=49)
    trinity = pentecost + timedelta(days=7)
    christ_the_king = _advent_sunday_1(year) - timedelta(days=7)
    transfiguration = ash_wed - timedelta(days=4)  # Sunday before Ash Wed
    palm_sunday = easter_sun - timedelta(days=7)

    # Christmastide and Advent (these can straddle the year boundary)
    advent_1_this_year = _advent_sunday_1(year)
    advent_1_prev_year = _advent_sunday_1(year - 1)
    epiphany_this_year = _epiphany_sunday(year)
    epiphany_next_year = _epiphany_sunday(year + 1)

    # Christmas season: from Christmas Day through the day before Epiphany Sunday
    # This Sunday might be in Christmas if it's between Dec 25 and Jan 5,
    # OR between this year's Advent 1 (which is in late Nov/early Dec) and Christmas
    if advent_1_this_year <= d < date_class(year, 12, 25):
        # Advent — number 1 through 4
        n = ((d - advent_1_this_year).days // 7) + 1
        names = ['First', 'Second', 'Third', 'Fourth']
        return f"{names[n - 1]} Sunday of Advent"

    # Sundays after Christmas (Dec 25 through Jan 5)
    if d >= date_class(year, 12, 25) or d < epiphany_this_year:
        # Could be First or Second Sunday after Christmas
        # First Sunday after Christmas: the Sunday on or after Dec 26
        if d.month == 12:
            return "First Sunday after Christmas"
        else:
            return "Second Sunday after Christmas"

    # Epiphany itself (if on Sunday) and Sundays after
    if d == epiphany_this_year:
        return "Baptism of the Lord" if epiphany_this_year > date_class(year, 1, 6) else "Epiphany of the Lord"
    if epiphany_this_year < d <= transfiguration:
        # First Sunday after Epiphany is Baptism of the Lord
        # Last is Transfiguration
        if d == transfiguration:
            return "Transfiguration Sunday"
        # Baptism = the Sunday on or after Jan 7 (when Jan 6 was already passed)
        baptism = epiphany_this_year + timedelta(days=7) if epiphany_this_year.day == 6 else epiphany_this_year
        if d == baptism:
            return "Baptism of the Lord"
        weeks_after_baptism = (d - baptism).days // 7
        ordinals = ['Second', 'Third', 'Fourth', 'Fifth', 'Sixth', 'Seventh', 'Eighth', 'Ninth']
        if 1 <= weeks_after_baptism <= len(ordinals):
            return f"{ordinals[weeks_after_baptism - 1]} Sunday after the Epiphany"
        return "Sunday after the Epiphany"

    # Lent
    if ash_wed <= d < palm_sunday:
        n = ((d - ash_wed).days // 7) + 1
        names = ['First', 'Second', 'Third', 'Fourth', 'Fifth']
        return f"{names[n - 1]} Sunday in Lent"
    if d == palm_sunday:
        return "Palm Sunday"
    if d == easter_sun:
        return "Easter Sunday"

    # Easter season
    if easter_sun < d < pentecost:
        n = ((d - easter_sun).days // 7) + 1
        names = ['Second', 'Third', 'Fourth', 'Fifth', 'Sixth', 'Seventh']
        if 1 <= n <= len(names):
            return f"{names[n - 1]} Sunday of Easter"
        if d == pentecost:
            return "Day of Pentecost"
        return "Easter Season"
    if d == pentecost:
        return "Day of Pentecost"
    if d == trinity:
        return "Trinity Sunday"
    if d == christ_the_king:
        return "Christ the King Sunday"

    # Season after Pentecost — Propers
    if trinity < d < christ_the_king:
        prop = _proper_number(d)
        if prop is not None:
            return f"Proper {prop}"

    # Late-year Advent fallback
    if d >= advent_1_this_year:
        return "First Sunday of Advent"

    return None