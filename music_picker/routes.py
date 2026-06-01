from .liturgy import liturgical_name
from .themes import get_theme_for_date

from datetime import date as date_class

from flask import Blueprint, abort, redirect, render_template, request, url_for

from .calendar_utils import (
    format_last_played,
    iso_to_db_parts,
    next_month,
    prev_month,
    season_for_date,
    sundays_in_month,
    to_sortable_date,
)
from .constants import MONTH_NAMES, PERFORMERS, SEASONS, SLOTS, season_palette
from .db import get_db
from .documents import generate_document_template, try_sync_doc
from .services import (
    get_past_pieces_for_season,
    get_repertoire_results,
    get_sunday_summary,
    is_library,
    matches_search,
)


bp = Blueprint('main', __name__)


@bp.route('/')
def index():
    season = request.args.get('season', '')
    slot = request.args.get('slot', '')
    search_q = request.args.get('q', '').strip()
    month_param = request.args.get('month', '')
    today = date_class.today()
    if month_param:
        try:
            y_str, m_str = month_param.split('-')
            view_year, view_month = int(y_str), int(m_str)
        except (ValueError, AttributeError):
            view_year, view_month = today.year, today.month
    else:
        view_year, view_month = today.year, today.month
    pmy, pmm = prev_month(view_year, view_month)
    nmy, nmm = next_month(view_year, view_month)

    sundays_list = []
    for d in sundays_in_month(view_year, view_month):
        summary = get_sunday_summary(d)
        sunday_season = season_for_date(d)
        sunday_liturgical = liturgical_name(d)
        theme_context = get_theme_for_date(
            d,
            liturgical_name=sunday_liturgical,
            season=sunday_season,
        )

        sundays_list.append({
            'iso': d.isoformat(),
            'display': d.strftime('%a, %b %-d'),
            'is_today': d == today,
            'is_past': d < today,
            'pieces': summary['pieces'],
            'occasion': summary['occasion'],
            'season': sunday_season,
            'liturgical': sunday_liturgical,
            'theme_context': theme_context,
        })

    unique_rows, count = get_repertoire_results(
        search_q=search_q,
        season=season,
        slot=slot,
        limit=None,
    )

    doc_status_rows = get_db().execute(
        "SELECT season_year, generated_at, last_synced_at FROM doc_paths ORDER BY season_year"
    ).fetchall()
    doc_status = {r['season_year']: dict(r) for r in doc_status_rows}

    return render_template(
        'index.html',
        rows=unique_rows,
        count=count,
        sundays=sundays_list,
        month_label=f"{MONTH_NAMES[view_month]} {view_year}",
        prev_month_iso=f"{pmy:04d}-{pmm:02d}",
        next_month_iso=f"{nmy:04d}-{nmm:02d}",
        seasons=SEASONS,
        slots=SLOTS,
        season=season,
        slot=slot,
        search_q=search_q,
        default_year=date_class.today().year,
        doc_status=doc_status,
        season_palette=season_palette,
    )


@bp.route('/generate', methods=['POST'])
def generate():
    season = request.form.get('season', '')
    year = int(request.form.get('year', date_class.today().year))
    if season not in SEASONS:
        abort(400, 'invalid season')
    try:
        success, message = generate_document_template(season, year)
    except Exception as e:
        success, message = False, f"Error during generation: {e}"
    return redirect(url_for('main.index', generated=('1' if success else '0'), msg=message))


@bp.route('/library/add', methods=['POST'])
def library_add():
    title = request.form.get('title', '').strip()
    if not title:
        return redirect(url_for('main.index'))
    composer = request.form.get('composer', '').strip()
    composer_dates = request.form.get('composer_dates', '').strip()
    source_file = request.form.get('source_file', '').strip()
    get_db().execute('''
        INSERT INTO pieces
            (season, calendar_year, date, occasion, slot, performer,
             chosen_by, title, composer, composer_dates, hymn_no,
             source_file, status, library_only)
        VALUES
            ('', NULL, '', '', '', '',
             'Michael', ?, ?, ?, '',
             ?, 'library', 1)
    ''', (title, composer, composer_dates, source_file))
    get_db().commit()
    return redirect(url_for('main.index', library_added='1', added_title=title))



def _table_columns(table):
    return [row[1] for row in get_db().execute(f"PRAGMA table_info({table})").fetchall()]


def _clean_form_value(value):
    return (value or "").strip()


def _find_or_create_personal_library_item(title, composer, composer_dates, season):
    """Create/update a canonical personal_library repertoire item."""
    title = _clean_form_value(title)
    composer = _clean_form_value(composer)
    composer_dates = _clean_form_value(composer_dates)
    season = _clean_form_value(season)

    if not title:
        return None

    db = get_db()

    existing = db.execute("""
        SELECT *
        FROM personal_library
        WHERE active=1
          AND lower(title)=lower(?)
          AND lower(coalesce(composer,''))=lower(?)
        ORDER BY id
        LIMIT 1
    """, (title, composer)).fetchone()

    if existing:
        db.execute("""
            UPDATE personal_library
            SET title=?,
                composer=?,
                composer_dates=?,
                season=?
            WHERE id=?
        """, (
            title,
            composer,
            composer_dates or existing['composer_dates'] or '',
            season or existing['season'] or '',
            existing['id'],
        ))
        return existing['id']

    db.execute("""
        INSERT INTO personal_library (
            title, composer, composer_dates, season, source_file, notes, active
        )
        VALUES (?, ?, ?, ?, 'Added from planning view', '', 1)
    """, (
        title,
        composer,
        composer_dates,
        season,
    ))

    return db.execute("SELECT last_insert_rowid()").fetchone()[0]


def _find_or_create_choir_item(title, composer, season_filter=None, occasion_filter=None, source_id=None):
    """Create/update choir_library item."""
    title = _clean_form_value(title)
    composer = _clean_form_value(composer)

    if not title:
        return None

    db = get_db()

    if source_id:
        row = db.execute("SELECT * FROM choir_library WHERE id=?", (source_id,)).fetchone()
        if row:
            db.execute("""
                UPDATE choir_library
                SET title=?,
                    composer=?
                WHERE id=?
            """, (title, composer, source_id))
            return source_id

    existing = db.execute("""
        SELECT id FROM choir_library
        WHERE active=1
          AND lower(title)=lower(?)
          AND lower(coalesce(composer,''))=lower(?)
        ORDER BY id
        LIMIT 1
    """, (title, composer)).fetchone()

    if existing:
        db.execute("""
            UPDATE choir_library
            SET title=?,
                composer=?
            WHERE id=?
        """, (title, composer, existing['id']))
        return existing['id']

    cols = _table_columns("choir_library")
    values = {
        "title": title,
        "composer": composer,
        "voicing": "",
        "difficulty": "",
        "season": season_filter or "",
        "style": "",
        "copies": "",
        "publisher": "",
        "year": "",
        "purchased": "",
        "instrumentation": "",
        "scripture": "",
        "choice": "Added from planning view",
        "active": 1,
        "season_filter": season_filter or "",
        "occasion_filter": occasion_filter or "",
    }

    insert_cols = [c for c in values if c in cols]
    placeholders = ", ".join(["?"] * len(insert_cols))
    sql = f"INSERT INTO choir_library ({', '.join(insert_cols)}) VALUES ({placeholders})"
    db.execute(sql, [values[c] for c in insert_cols])
    return db.execute("SELECT last_insert_rowid()").fetchone()[0]


def _find_or_create_bell_item(title, composer_arranger, source_id=None):
    """Create/update bell_library item."""
    title = _clean_form_value(title)
    composer_arranger = _clean_form_value(composer_arranger)

    if not title:
        return None

    db = get_db()

    if source_id:
        row = db.execute("SELECT * FROM bell_library WHERE id=?", (source_id,)).fetchone()
        if row:
            db.execute("""
                UPDATE bell_library
                SET title=?,
                    composer_arranger=?
                WHERE id=?
            """, (title, composer_arranger, source_id))
            return source_id

    existing = db.execute("""
        SELECT id FROM bell_library
        WHERE active=1
          AND lower(title)=lower(?)
          AND lower(coalesce(composer_arranger,''))=lower(?)
        ORDER BY id
        LIMIT 1
    """, (title, composer_arranger)).fetchone()

    if existing:
        db.execute("""
            UPDATE bell_library
            SET title=?,
                composer_arranger=?
            WHERE id=?
        """, (title, composer_arranger, existing['id']))
        return existing['id']

    db.execute("""
        INSERT INTO bell_library (title, composer_arranger, active)
        VALUES (?, ?, 1)
    """, (title, composer_arranger))
    return db.execute("SELECT last_insert_rowid()").fetchone()[0]


def _library_target_for_season(form_season):
    """Keep current app values. UI may display Pentecost as General / OT."""
    return form_season or ""


@bp.route('/plan/<iso>', methods=['GET', 'POST'])

def plan(iso):
    try:
        y, m, d = [int(x) for x in iso.split('-')]
        the_date = date_class(y, m, d)
    except (ValueError, TypeError):
        abort(404)
    date_str, year = iso_to_db_parts(iso)
    form_season = season_for_date(the_date)
    if request.method == 'POST':
        for slot in SLOTS:
            get_db().execute(
                "DELETE FROM pieces WHERE calendar_year=? AND date=? AND slot=? AND chosen_by='Michael' AND (library_only=0 OR library_only IS NULL)",
                (year, date_str, slot),
            )
            title = request.form.get(f'title_{slot}', '').strip()
            if not title:
                continue
            composer = request.form.get(f'composer_{slot}', '').strip()
            dates = request.form.get(f'composer_dates_{slot}', '').strip()
            performer = request.form.get(f'performer_{slot}', 'Unspecified')

            source_type = request.form.get(f'source_type_{slot}', '').strip()
            source_id_raw = request.form.get(f'source_id_{slot}', '').strip()
            source_id = int(source_id_raw) if source_id_raw.isdigit() else None

            add_to_library = request.form.get(f'add_to_library_{slot}') == '1'
            library_target = request.form.get(f'library_target_{slot}', 'personal').strip() or 'personal'
            season_value = request.form.get('season', form_season)
            occasion_value = request.form.get('occasion', '').strip()

            # If this was selected from an existing source, default to updating that source.
            if source_type in ('personal', 'choir', 'bells'):
                library_target = source_type
                add_to_library = True

            # Manual entries default to being added to the selected library if checked.
            if add_to_library:
                if library_target == 'choir':
                    source_type = 'choir'
                    source_id = _find_or_create_choir_item(
                        title,
                        composer,
                        season_filter=_library_target_for_season(season_value),
                        occasion_filter=occasion_value,
                        source_id=source_id if source_type == 'choir' else None,
                    )
                elif library_target == 'bells':
                    source_type = 'bells'
                    source_id = _find_or_create_bell_item(
                        title,
                        composer,
                        source_id=source_id if source_type == 'bells' else None,
                    )
                else:
                    source_type = 'personal'
                    source_id = _find_or_create_personal_library_item(
                        title,
                        composer,
                        dates,
                        season_value,
                    )

            today = date_class.today()
            status = 'scheduled' if (year, m, d) >= (today.year, today.month, today.day) else 'played'
            get_db().execute('''INSERT INTO pieces (season, calendar_year, date, occasion, slot, performer, chosen_by, title, composer, composer_dates, status, library_only, source_type, source_id)
                VALUES (?, ?, ?, ?, ?, ?, 'Michael', ?, ?, ?, ?, 0, ?, ?)''',
                (season_value, year, date_str, request.form.get('occasion', ''),
                 slot, performer, title, composer, dates, status, source_type or None, source_id))
        get_db().commit()
        try_sync_doc(form_season, year)
        return redirect(url_for('main.index', month=f"{y:04d}-{m:02d}", saved='1', synced='1'))
    rows = get_db().execute("SELECT * FROM pieces WHERE calendar_year=? AND date=?", (year, date_str)).fetchall()
    slot_data = {s: {'title': '', 'composer': '', 'composer_dates': '', 'performer': 'Unspecified', 'source_type': '', 'source_id': ''} for s in SLOTS}
    hymns = []
    occasion = ''
    for r in rows:
        if is_library(r):
            continue
        if r['slot'] == 'Hymn':
            hymns.append({'title': r['title'], 'hymn_no': r['hymn_no']})
        elif r['slot'] in SLOTS and r['chosen_by'] == 'Michael':
            slot_data[r['slot']] = {'title': r['title'], 'composer': r['composer'],
                                    'composer_dates': r['composer_dates'], 'performer': r['performer'] or 'Unspecified',
                                    'source_type': r['source_type'] if 'source_type' in r.keys() else '',
                                    'source_id': r['source_id'] if 'source_id' in r.keys() else ''}
        if r['occasion'] and not occasion:
            occasion = r['occasion']
    filter_season_raw = request.args.get('filter_season')
    if filter_season_raw is None:
        filter_season = form_season
    elif filter_season_raw == '__all__':
        filter_season = ''
    else:
        filter_season = filter_season_raw
    filter_slot = request.args.get('filter_slot', '')
    filter_occasion = request.args.get('filter_occasion', '')
    filter_voicing = request.args.get('filter_voicing', '')
    filter_difficulty = request.args.get('filter_difficulty', '')
    sidebar_library = request.args.get('library', 'personal')
    if sidebar_library not in ('personal', 'choir', 'bells'):
        sidebar_library = 'personal'

    search_q = request.args.get('q', '').strip()
    show_all = request.args.get('all_past') == '1'
    limit = None if show_all else 25

    past_pieces, past_total = get_past_pieces_for_season(
        filter_season if filter_season else None,
        search_q=search_q,
        limit=limit,
        slot=filter_slot,
    )

    choir_rows = []
    bell_rows = []
    choir_total = 0
    bell_total = 0

    if sidebar_library == 'choir':
        choir_where = ["active=1"]
        choir_params = []

        if filter_season:
            if filter_season == "Advent/Christmas":
                choir_where.append("season_filter IN (?, ?)")
                choir_params.extend(["Advent", "Christmas"])
            else:
                choir_where.append("season_filter = ?")
                choir_params.append(filter_season)

        if filter_occasion:
            choir_where.append("occasion_filter = ?")
            choir_params.append(filter_occasion)

        if filter_voicing:
            choir_where.append("voicing = ?")
            choir_params.append(filter_voicing)

        if filter_difficulty:
            choir_where.append("difficulty = ?")
            choir_params.append(filter_difficulty)

        if search_q:
            like = f"%{search_q}%"
            choir_where.append("""(
                title LIKE ?
                OR composer LIKE ?
                OR voicing LIKE ?
                OR season LIKE ?
                OR season_filter LIKE ?
                OR occasion_filter LIKE ?
                OR style LIKE ?
                OR publisher LIKE ?
                OR instrumentation LIKE ?
                OR scripture LIKE ?
                OR choice LIKE ?
            )""")
            choir_params.extend([like, like, like, like, like, like, like, like, like, like, like])

        choir_count_sql = f"""
            SELECT COUNT(*)
            FROM choir_library
            WHERE {' AND '.join(choir_where)}
        """
        choir_total = get_db().execute(choir_count_sql, choir_params).fetchone()[0]

        choir_sql = f"""
            SELECT * FROM choir_library
            WHERE {' AND '.join(choir_where)}
            ORDER BY title COLLATE NOCASE
            LIMIT 100
        """

        choir_rows = get_db().execute(choir_sql, choir_params).fetchall()

    if sidebar_library == 'bells':
        if search_q:
            like = f"%{search_q}%"
            bell_rows = get_db().execute("""
                SELECT * FROM bell_library
                WHERE active=1 AND (
                    title LIKE ?
                    OR composer_arranger LIKE ?
                )
                ORDER BY title COLLATE NOCASE
                LIMIT 100
            """, (like, like)).fetchall()
        else:
            bell_rows = get_db().execute("""
                SELECT * FROM bell_library
                WHERE active=1
                ORDER BY title COLLATE NOCASE
                LIMIT 100
            """).fetchall()
        bell_total = len(bell_rows)

    past_truncated = (not show_all) and past_total > 25
    occasion_options = [r[0] for r in get_db().execute("""
        SELECT DISTINCT occasion_filter
        FROM choir_library
        WHERE active=1
          AND occasion_filter IS NOT NULL
          AND occasion_filter != ''
        ORDER BY occasion_filter COLLATE NOCASE
    """).fetchall()]

    choir_voicing_options = [r[0] for r in get_db().execute("""
        SELECT DISTINCT voicing
        FROM choir_library
        WHERE active=1
          AND voicing IS NOT NULL
          AND voicing != ''
        ORDER BY voicing COLLATE NOCASE
    """).fetchall()]

    choir_difficulty_options = [r[0] for r in get_db().execute("""
        SELECT DISTINCT difficulty
        FROM choir_library
        WHERE active=1
          AND difficulty IS NOT NULL
          AND difficulty != ''
          AND difficulty != 'Unknown'
        ORDER BY difficulty COLLATE NOCASE
    """).fetchall()]

    liturgical = liturgical_name(the_date)
    sunday_theme = get_theme_for_date(the_date, liturgical_name=liturgical, season=form_season)
    return render_template('plan.html', iso=iso, display_date=the_date.strftime('%A, %B %-d, %Y'),
        slot_data=slot_data, slot_names=SLOTS, hymns=hymns, occasion=occasion, form_season=form_season,
        seasons=SEASONS, performers=PERFORMERS, filter_season=filter_season,
        filter_slot=filter_slot, filter_occasion=filter_occasion, filter_voicing=filter_voicing, filter_difficulty=filter_difficulty, sidebar_library=sidebar_library, search_q=search_q,
        past_pieces=past_pieces, past_total=past_total, past_truncated=past_truncated,
        choir_rows=choir_rows, choir_total=choir_total, occasion_options=occasion_options, choir_voicing_options=choir_voicing_options, choir_difficulty_options=choir_difficulty_options,
        bell_rows=bell_rows, bell_total=bell_total,
        season_palette=season_palette, liturgical=liturgical, sunday_theme=sunday_theme)



@bp.route('/libraries')
def libraries():
    choir_count = get_db().execute("SELECT COUNT(*) FROM choir_library WHERE active=1").fetchone()[0]
    bell_count = get_db().execute("SELECT COUNT(*) FROM bell_library WHERE active=1").fetchone()[0]
    return render_template('libraries.html', choir_count=choir_count, bell_count=bell_count)


@bp.route('/libraries/choir')
def choir_library():
    q = request.args.get('q', '').strip()
    season = request.args.get('season', '').strip()
    voicing = request.args.get('voicing', '').strip()
    style = request.args.get('style', '').strip()
    difficulty = request.args.get('difficulty', '').strip()

    where = ["active=1"]
    params = []

    if q:
        like = f"%{q}%"
        where.append("""(
            title LIKE ?
            OR composer LIKE ?
            OR publisher LIKE ?
            OR instrumentation LIKE ?
            OR scripture LIKE ?
            OR choice LIKE ?
        )""")
        params.extend([like, like, like, like, like, like])

    if season:
        where.append("season = ?")
        params.append(season)

    if voicing:
        where.append("voicing = ?")
        params.append(voicing)

    if style:
        where.append("style = ?")
        params.append(style)

    if difficulty:
        where.append("difficulty = ?")
        params.append(difficulty)

    sql = f"""
        SELECT * FROM choir_library
        WHERE {' AND '.join(where)}
        ORDER BY title COLLATE NOCASE
    """
    rows = get_db().execute(sql, params).fetchall()

    seasons = [r[0] for r in get_db().execute(
        "SELECT DISTINCT season FROM choir_library WHERE active=1 AND season IS NOT NULL AND season != '' ORDER BY season COLLATE NOCASE"
    ).fetchall()]
    voicings = [r[0] for r in get_db().execute(
        "SELECT DISTINCT voicing FROM choir_library WHERE active=1 AND voicing IS NOT NULL AND voicing != '' ORDER BY voicing COLLATE NOCASE"
    ).fetchall()]
    styles = [r[0] for r in get_db().execute(
        "SELECT DISTINCT style FROM choir_library WHERE active=1 AND style IS NOT NULL AND style != '' ORDER BY style COLLATE NOCASE"
    ).fetchall()]
    difficulties = [r[0] for r in get_db().execute(
        "SELECT DISTINCT difficulty FROM choir_library WHERE active=1 AND difficulty IS NOT NULL AND difficulty != '' ORDER BY difficulty COLLATE NOCASE"
    ).fetchall()]

    return render_template(
        'choir_library.html',
        rows=rows,
        q=q,
        season=season,
        voicing=voicing,
        style=style,
        difficulty=difficulty,
        seasons=seasons,
        voicings=voicings,
        styles=styles,
        difficulties=difficulties,
    )


@bp.route('/libraries/choir/new', methods=['GET', 'POST'])
def choir_library_new():
    if request.method == 'POST':
        get_db().execute("""
            INSERT INTO choir_library (
                title, voicing, difficulty, season, style, copies,
                composer, publisher, year, purchased, instrumentation,
                scripture, choice, active
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
        """, (
            request.form.get('title', '').strip(),
            request.form.get('voicing', '').strip(),
            request.form.get('difficulty', '').strip(),
            request.form.get('season', '').strip(),
            request.form.get('style', '').strip(),
            request.form.get('copies', '').strip(),
            request.form.get('composer', '').strip(),
            request.form.get('publisher', '').strip(),
            request.form.get('year', '').strip(),
            request.form.get('purchased', '').strip(),
            request.form.get('instrumentation', '').strip(),
            request.form.get('scripture', '').strip(),
            request.form.get('choice', '').strip(),
        ))
        get_db().commit()
        return redirect(url_for('main.choir_library'))

    return render_template('choir_library_form.html', row=None, mode='new')



@bp.route('/libraries/choir/<int:item_id>', methods=['GET', 'POST'])
def choir_library_detail(item_id):
    row = get_db().execute("SELECT * FROM choir_library WHERE id=? AND active=1", (item_id,)).fetchone()
    if not row:
        abort(404)

    if request.method == 'POST':
        iso = request.form.get('date', '').strip()
        slot = request.form.get('slot', '').strip()
        performer = request.form.get('performer', 'Chancel Choir').strip() or 'Chancel Choir'
        occasion = request.form.get('occasion', '').strip()

        try:
            y, m, d = [int(x) for x in iso.split('-')]
            the_date = date_class(y, m, d)
        except (ValueError, TypeError):
            abort(400)

        if slot not in SLOTS:
            abort(400)

        date_str, year = iso_to_db_parts(iso)
        today = date_class.today()
        status = 'scheduled' if (year, m, d) >= (today.year, today.month, today.day) else 'played'
        form_season = season_for_date(the_date)

        # Replace Michael's existing entry for this date/slot, same behavior as plan page.
        get_db().execute(
            "DELETE FROM pieces WHERE calendar_year=? AND date=? AND slot=? AND chosen_by='Michael' AND (library_only=0 OR library_only IS NULL)",
            (year, date_str, slot),
        )

        get_db().execute("""
            INSERT INTO pieces (
                season, calendar_year, date, occasion, slot, performer,
                chosen_by, title, composer, composer_dates, status, library_only
            )
            VALUES (?, ?, ?, ?, ?, ?, 'Michael', ?, ?, '', ?, 0)
        """, (
            form_season,
            year,
            date_str,
            occasion,
            slot,
            performer,
            row['title'],
            row['composer'] or '',
            status,
        ))

        get_db().commit()
        return redirect(url_for('main.plan', iso=iso))

    return render_template(
        'choir_library_detail.html',
        row=row,
        slot_names=SLOTS,
        performers=PERFORMERS,
    )


@bp.route('/libraries/bells/<int:item_id>', methods=['GET', 'POST'])
def bell_library_detail(item_id):
    row = get_db().execute("SELECT * FROM bell_library WHERE id=? AND active=1", (item_id,)).fetchone()
    if not row:
        abort(404)

    if request.method == 'POST':
        iso = request.form.get('date', '').strip()
        slot = request.form.get('slot', '').strip()
        performer = request.form.get('performer', 'Handbells').strip() or 'Handbells'
        occasion = request.form.get('occasion', '').strip()

        try:
            y, m, d = [int(x) for x in iso.split('-')]
            the_date = date_class(y, m, d)
        except (ValueError, TypeError):
            abort(400)

        if slot not in SLOTS:
            abort(400)

        date_str, year = iso_to_db_parts(iso)
        today = date_class.today()
        status = 'scheduled' if (year, m, d) >= (today.year, today.month, today.day) else 'played'
        form_season = season_for_date(the_date)

        get_db().execute(
            "DELETE FROM pieces WHERE calendar_year=? AND date=? AND slot=? AND chosen_by='Michael' AND (library_only=0 OR library_only IS NULL)",
            (year, date_str, slot),
        )

        get_db().execute("""
            INSERT INTO pieces (
                season, calendar_year, date, occasion, slot, performer,
                chosen_by, title, composer, composer_dates, status, library_only
            )
            VALUES (?, ?, ?, ?, ?, ?, 'Michael', ?, ?, '', ?, 0)
        """, (
            form_season,
            year,
            date_str,
            occasion,
            slot,
            performer,
            row['title'],
            row['composer_arranger'] or '',
            status,
        ))

        get_db().commit()
        return redirect(url_for('main.plan', iso=iso))

    return render_template(
        'bell_library_detail.html',
        row=row,
        slot_names=SLOTS,
        performers=PERFORMERS,
    )

@bp.route('/libraries/choir/<int:item_id>/edit', methods=['GET', 'POST'])
def choir_library_edit(item_id):
    row = get_db().execute("SELECT * FROM choir_library WHERE id=?", (item_id,)).fetchone()
    if not row:
        abort(404)

    if request.method == 'POST':
        if request.form.get('delete') == '1':
            get_db().execute("UPDATE choir_library SET active=0 WHERE id=?", (item_id,))
            get_db().commit()
            return redirect(url_for('main.choir_library'))

        get_db().execute("""
            UPDATE choir_library
            SET title=?, voicing=?, difficulty=?, season=?, style=?, copies=?,
                composer=?, publisher=?, year=?, purchased=?, instrumentation=?,
                scripture=?, choice=?
            WHERE id=?
        """, (
            request.form.get('title', '').strip(),
            request.form.get('voicing', '').strip(),
            request.form.get('difficulty', '').strip(),
            request.form.get('season', '').strip(),
            request.form.get('style', '').strip(),
            request.form.get('copies', '').strip(),
            request.form.get('composer', '').strip(),
            request.form.get('publisher', '').strip(),
            request.form.get('year', '').strip(),
            request.form.get('purchased', '').strip(),
            request.form.get('instrumentation', '').strip(),
            request.form.get('scripture', '').strip(),
            request.form.get('choice', '').strip(),
            item_id,
        ))
        get_db().commit()
        return redirect(url_for('main.choir_library'))

    return render_template('choir_library_form.html', row=row, mode='edit')


@bp.route('/libraries/bells')
def bell_library():
    q = request.args.get('q', '').strip()
    db = get_db()

    if q:
        like = f"%{q}%"
        rows = db.execute("""
            SELECT * FROM bell_library
            WHERE active=1 AND (
                title LIKE ?
                OR composer_arranger LIKE ?
            )
            ORDER BY title COLLATE NOCASE
        """, (like, like)).fetchall()
    else:
        rows = db.execute("""
            SELECT * FROM bell_library
            WHERE active=1
            ORDER BY title COLLATE NOCASE
        """).fetchall()

    return render_template('bell_library.html', rows=rows, q=q)


@bp.route('/libraries/bells/new', methods=['GET', 'POST'])
def bell_library_new():
    if request.method == 'POST':
        get_db().execute("""
            INSERT INTO bell_library (title, composer_arranger, active)
            VALUES (?, ?, 1)
        """, (
            request.form.get('title', '').strip(),
            request.form.get('composer_arranger', '').strip(),
        ))
        get_db().commit()
        return redirect(url_for('main.bell_library'))

    return render_template('bell_library_form.html', row=None, mode='new')


@bp.route('/libraries/bells/<int:item_id>/edit', methods=['GET', 'POST'])
def bell_library_edit(item_id):
    row = get_db().execute("SELECT * FROM bell_library WHERE id=?", (item_id,)).fetchone()
    if not row:
        abort(404)

    if request.method == 'POST':
        if request.form.get('delete') == '1':
            get_db().execute("UPDATE bell_library SET active=0 WHERE id=?", (item_id,))
            get_db().commit()
            return redirect(url_for('main.bell_library'))

        get_db().execute("""
            UPDATE bell_library
            SET title=?, composer_arranger=?
            WHERE id=?
        """, (
            request.form.get('title', '').strip(),
            request.form.get('composer_arranger', '').strip(),
            item_id,
        ))
        get_db().commit()
        return redirect(url_for('main.bell_library'))

    return render_template('bell_library_form.html', row=row, mode='edit')

@bp.route('/piece/<path:title>')
def piece_detail(title):
    history = get_db().execute("SELECT * FROM pieces WHERE title = ? AND chosen_by = 'Michael'", (title,)).fetchall()
    if not history:
        abort(404)

    def sort_key(r):
        if is_library(r):
            return (-1, 0, 0)
        return to_sortable_date(r)

    history = sorted(history, key=sort_key, reverse=True)
    first = history[0]
    is_lib = all(is_library(r) for r in history)
    source = first['source_file'] if 'source_file' in first.keys() else ''
    return render_template('detail.html', title=title, composer=first['composer'],
                           composer_dates=first['composer_dates'], history=history,
                           is_library=is_lib, source_file=source)


@bp.route('/edit/<int:piece_id>', methods=['GET', 'POST'])
def edit(piece_id):
    row = get_db().execute("SELECT * FROM pieces WHERE id = ?", (piece_id,)).fetchone()
    if not row:
        abort(404)
    back_url = request.args.get('from') or request.form.get('from') or url_for('main.index')
    if request.method == 'POST':
        new_title = request.form.get('title', '').strip()
        new_composer = request.form.get('composer', '').strip()
        new_dates = request.form.get('composer_dates', '').strip()
        new_slot = request.form.get('slot', row['slot'])
        new_performer = request.form.get('performer', row['performer'] or 'Unspecified')
        new_occasion = request.form.get('occasion', '').strip()
        get_db().execute('''UPDATE pieces SET title=?, composer=?, composer_dates=?, slot=?, performer=?, occasion=? WHERE id=?''',
                         (new_title, new_composer, new_dates, new_slot, new_performer, new_occasion, piece_id))
        get_db().commit()
        if row['season'] and row['calendar_year']:
            try_sync_doc(row['season'], row['calendar_year'])
        if new_title and new_title != row['title']:
            return redirect(url_for('main.piece_detail', title=new_title))
        return redirect(back_url)
    return render_template('edit.html', row=row, slots=SLOTS, performers=PERFORMERS, back_url=back_url)


@bp.route('/delete/<int:piece_id>', methods=['POST'])
def delete(piece_id):
    row = get_db().execute("SELECT season, calendar_year FROM pieces WHERE id = ?", (piece_id,)).fetchone()
    if not row:
        abort(404)
    get_db().execute("DELETE FROM pieces WHERE id = ?", (piece_id,))
    get_db().commit()
    if row['season'] and row['calendar_year']:
        try_sync_doc(row['season'], row['calendar_year'])
    back_url = request.form.get('from') or url_for('main.index')
    return redirect(back_url + ('&' if '?' in back_url else '?') + 'deleted=1')


@bp.route('/delete-title', methods=['POST'])
def delete_title():
    title = request.form.get('title', '')
    if not title:
        abort(400)
    affected = get_db().execute("SELECT DISTINCT season, calendar_year FROM pieces WHERE title=?", (title,)).fetchall()
    get_db().execute("DELETE FROM pieces WHERE title = ?", (title,))
    get_db().commit()
    for r in affected:
        if r['season'] and r['calendar_year']:
            try_sync_doc(r['season'], r['calendar_year'])
    return redirect(url_for('main.index', deleted='1'))


