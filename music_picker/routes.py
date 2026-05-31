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
            today = date_class.today()
            status = 'scheduled' if (year, m, d) >= (today.year, today.month, today.day) else 'played'
            get_db().execute('''INSERT INTO pieces (season, calendar_year, date, occasion, slot, performer, chosen_by, title, composer, composer_dates, status, library_only)
                VALUES (?, ?, ?, ?, ?, ?, 'Michael', ?, ?, ?, ?, 0)''',
                (request.form.get('season', form_season), year, date_str, request.form.get('occasion', ''),
                 slot, performer, title, composer, dates, status))
        get_db().commit()
        try_sync_doc(form_season, year)
        return redirect(url_for('main.index', month=f"{y:04d}-{m:02d}", saved='1', synced='1'))
    rows = get_db().execute("SELECT * FROM pieces WHERE calendar_year=? AND date=?", (year, date_str)).fetchall()
    slot_data = {s: {'title': '', 'composer': '', 'composer_dates': '', 'performer': 'Unspecified'} for s in SLOTS}
    hymns = []
    occasion = ''
    for r in rows:
        if is_library(r):
            continue
        if r['slot'] == 'Hymn':
            hymns.append({'title': r['title'], 'hymn_no': r['hymn_no']})
        elif r['slot'] in SLOTS and r['chosen_by'] == 'Michael':
            slot_data[r['slot']] = {'title': r['title'], 'composer': r['composer'],
                                    'composer_dates': r['composer_dates'], 'performer': r['performer'] or 'Unspecified'}
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
    search_q = request.args.get('q', '').strip()
    show_all = request.args.get('all_past') == '1'
    limit = None if show_all else 25
    past_pieces, past_total = get_past_pieces_for_season(
        filter_season if filter_season else None,
        search_q=search_q,
        limit=limit,
        slot=filter_slot,
    )
    past_truncated = (not show_all) and past_total > 25
    liturgical = liturgical_name(the_date)
    sunday_theme = get_theme_for_date(the_date, liturgical_name=liturgical, season=form_season)
    return render_template('plan.html', iso=iso, display_date=the_date.strftime('%A, %B %-d, %Y'),
        slot_data=slot_data, slot_names=SLOTS, hymns=hymns, occasion=occasion, form_season=form_season,
        seasons=SEASONS, performers=PERFORMERS, filter_season=filter_season,
        filter_slot=filter_slot, search_q=search_q,
        past_pieces=past_pieces, past_total=past_total, past_truncated=past_truncated,
        season_palette=season_palette, liturgical=liturgical, sunday_theme=sunday_theme)


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


@bp.route('/libraries')
def libraries():
    return render_template('libraries.html')


@bp.route('/libraries/choir')
def choir_library():
    q = request.args.get('q', '').strip()
    db = get_db()

    if q:
        like = f"%{q}%"
        rows = db.execute("""
            SELECT * FROM choir_library
            WHERE active=1 AND (
                title LIKE ?
                OR composer LIKE ?
                OR voicing LIKE ?
                OR season LIKE ?
                OR style LIKE ?
                OR publisher LIKE ?
                OR instrumentation LIKE ?
                OR scripture LIKE ?
                OR choice LIKE ?
            )
            ORDER BY title COLLATE NOCASE
        """, (like, like, like, like, like, like, like, like, like)).fetchall()
    else:
        rows = db.execute("""
            SELECT * FROM choir_library
            WHERE active=1
            ORDER BY title COLLATE NOCASE
        """).fetchall()

    return render_template('choir_library.html', rows=rows, q=q)


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
