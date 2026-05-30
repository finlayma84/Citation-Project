SEASONS = ['Advent/Christmas', 'Epiphany', 'Lent', 'Easter', 'Pentecost']
SLOTS = ['Prelude', 'Min Music', 'Offering', 'Postlude']
PERFORMERS = ['Unspecified', 'Choir', 'Vocal solo', 'Instrumental', 'Bells']

MONTHS_REV = ['', 'JAN', 'FEB', 'MAR', 'APR', 'MAY', 'JUN',
              'JUL', 'AUG', 'SEP', 'OCT', 'NOV', 'DEC']
MONTHS = {m: i for i, m in enumerate(MONTHS_REV) if m}
MONTH_NAMES = ['', 'January', 'February', 'March', 'April', 'May', 'June',
               'July', 'August', 'September', 'October', 'November', 'December']

SEASON_COLORS = {
    'Advent/Christmas': {'accent': 'var(--season-advent)',    'tint_bg': 'var(--season-advent-bg)',    'label': 'Advent · Christmas'},
    'Epiphany':         {'accent': 'var(--season-epiphany)',  'tint_bg': 'var(--season-epiphany-bg)',  'label': 'Epiphany'},
    'Lent':             {'accent': 'var(--season-lent)',      'tint_bg': 'var(--season-lent-bg)',      'label': 'Lent'},
    'Easter':           {'accent': 'var(--season-easter)',    'tint_bg': 'var(--season-easter-bg)',    'label': 'Easter'},
    'Pentecost':        {'accent': 'var(--season-pentecost)', 'tint_bg': 'var(--season-pentecost-bg)', 'label': 'Pentecost'},
}


def season_palette(season):
    return SEASON_COLORS.get(season, SEASON_COLORS['Pentecost'])
