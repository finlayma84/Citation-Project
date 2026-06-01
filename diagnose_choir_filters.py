"""
Diagnose why plan-view Choir filters for voicing/difficulty are not working.

Run:
    python diagnose_choir_filters.py
"""

from __future__ import annotations

import re
import sqlite3
from pathlib import Path

from music_picker import create_app


DB_PATH = Path("repertoire.db")
TEST_ISO = "2026-12-13"  # arbitrary Sunday-ish plan page date


def connect():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    return con


def section(title):
    print()
    print("=" * 90)
    print(title)
    print("=" * 90)


def show_counts():
    section("1. Choir library metadata counts")

    with connect() as con:
        print("Voicing values:")
        rows = con.execute("""
            SELECT voicing, COUNT(*) AS n
            FROM choir_library
            WHERE active=1
            GROUP BY voicing
            ORDER BY n DESC, voicing
        """).fetchall()

        for r in rows:
            print(f"  {r['voicing']!r}: {r['n']}")

        print()
        print("Difficulty values:")
        rows = con.execute("""
            SELECT difficulty, COUNT(*) AS n
            FROM choir_library
            WHERE active=1
            GROUP BY difficulty
            ORDER BY n DESC, difficulty
        """).fetchall()

        for r in rows:
            print(f"  {r['difficulty']!r}: {r['n']}")

        print()
        print("Example rows with both voicing and difficulty:")
        rows = con.execute("""
            SELECT id, title, composer, voicing, difficulty, season_filter, occasion_filter
            FROM choir_library
            WHERE active=1
              AND coalesce(voicing,'') != ''
              AND coalesce(difficulty,'') != ''
            ORDER BY title
            LIMIT 15
        """).fetchall()

        for r in rows:
            print(dict(r))


def pick_test_values():
    with connect() as con:
        voicing_row = con.execute("""
            SELECT voicing, COUNT(*) AS n
            FROM choir_library
            WHERE active=1
              AND coalesce(voicing,'') != ''
            GROUP BY voicing
            ORDER BY n DESC
            LIMIT 1
        """).fetchone()

        difficulty_row = con.execute("""
            SELECT difficulty, COUNT(*) AS n
            FROM choir_library
            WHERE active=1
              AND coalesce(difficulty,'') != ''
              AND difficulty != 'Unknown'
            GROUP BY difficulty
            ORDER BY n DESC
            LIMIT 1
        """).fetchone()

    voicing = voicing_row["voicing"] if voicing_row else ""
    difficulty = difficulty_row["difficulty"] if difficulty_row else ""

    return voicing, difficulty


def direct_sql_check(voicing, difficulty):
    section("2. Direct SQL filter check")

    with connect() as con:
        total = con.execute("""
            SELECT COUNT(*)
            FROM choir_library
            WHERE active=1
        """).fetchone()[0]

        voice_count = con.execute("""
            SELECT COUNT(*)
            FROM choir_library
            WHERE active=1
              AND voicing=?
        """, (voicing,)).fetchone()[0]

        diff_count = con.execute("""
            SELECT COUNT(*)
            FROM choir_library
            WHERE active=1
              AND difficulty=?
        """, (difficulty,)).fetchone()[0]

        both_count = con.execute("""
            SELECT COUNT(*)
            FROM choir_library
            WHERE active=1
              AND voicing=?
              AND difficulty=?
        """, (voicing, difficulty)).fetchone()[0]

        print(f"Chosen voicing: {voicing!r}")
        print(f"Chosen difficulty: {difficulty!r}")
        print(f"Total active choir rows: {total}")
        print(f"Rows matching voicing: {voice_count}")
        print(f"Rows matching difficulty: {diff_count}")
        print(f"Rows matching both: {both_count}")

        print()
        print("Examples matching voicing:")
        rows = con.execute("""
            SELECT id, title, composer, voicing, difficulty
            FROM choir_library
            WHERE active=1
              AND voicing=?
            ORDER BY title
            LIMIT 10
        """, (voicing,)).fetchall()

        for r in rows:
            print(dict(r))


def fetch_plan(client, params):
    response = client.get(f"/plan/{TEST_ISO}", query_string=params)
    html = response.get_data(as_text=True)

    print(f"GET /plan/{TEST_ISO}?{params}")
    print(f"Status: {response.status_code}")
    if response.status_code != 200:
        print(html[:1000])
        raise SystemExit("Plan page did not load.")

    return html


def extract_count_line(html):
    match = re.search(r'<p id="sidebar-count"[^>]*>(.*?)</p>', html, flags=re.S)
    if not match:
        return "(sidebar-count not found)"

    text = re.sub(r"<.*?>", "", match.group(1))
    text = " ".join(text.split())
    return text


def rendered_route_check(voicing, difficulty):
    section("3. Flask route/rendered HTML check")

    app = create_app()
    app.config.update(TESTING=True)

    with app.test_client() as client:
        base_params = {
            "library": "choir",
            "filter_season": "__all__",
        }

        html_all = fetch_plan(client, base_params)
        print("Count line:", extract_count_line(html_all))
        print("Has voicing dropdown?", 'name="filter_voicing"' in html_all)
        print("Has difficulty dropdown?", 'name="filter_difficulty"' in html_all)

        print()
        voice_params = {
            "library": "choir",
            "filter_season": "__all__",
            "filter_voicing": voicing,
        }
        html_voice = fetch_plan(client, voice_params)
        print("Count line:", extract_count_line(html_voice))
        print(f"Selected voicing option present? {'value=\"' + voicing + '\" selected' in html_voice}")

        print()
        diff_params = {
            "library": "choir",
            "filter_season": "__all__",
            "filter_difficulty": difficulty,
        }
        html_diff = fetch_plan(client, diff_params)
        print("Count line:", extract_count_line(html_diff))
        print(f"Selected difficulty option present? {'value=\"' + difficulty + '\" selected' in html_diff}")

        print()
        both_params = {
            "library": "choir",
            "filter_season": "__all__",
            "filter_voicing": voicing,
            "filter_difficulty": difficulty,
        }
        html_both = fetch_plan(client, both_params)
        print("Count line:", extract_count_line(html_both))

        print()
        print("Important HTML/route clues:")
        for needle in [
            "filter_voicing",
            "filter_difficulty",
            "choir pieces",
            "All voicings",
            "All levels",
        ]:
            print(f"  {needle!r}: {needle in html_both}")


def inspect_routes_source():
    section("4. Source-code sanity checks")

    routes = Path("music_picker/routes.py").read_text()
    plan = Path("music_picker/templates/plan.html").read_text()

    checks = [
        ("routes.py reads filter_voicing", "filter_voicing = request.args.get('filter_voicing'" in routes),
        ("routes.py reads filter_difficulty", "filter_difficulty = request.args.get('filter_difficulty'" in routes),
        ("routes.py filters voicing", 'choir_where.append("voicing = ?")' in routes),
        ("routes.py filters difficulty", 'choir_where.append("difficulty = ?")' in routes),
        ("routes.py passes filter_voicing", "filter_voicing=filter_voicing" in routes),
        ("routes.py passes choir_voicing_options", "choir_voicing_options=choir_voicing_options" in routes),
        ("plan.html has voicing select", 'name="filter_voicing"' in plan),
        ("plan.html has difficulty select", 'name="filter_difficulty"' in plan),
        ("plan.html JS sends filter_voicing", "filter_voicing:" in plan),
        ("plan.html JS sends filter_difficulty", "filter_difficulty:" in plan),
    ]

    for label, ok in checks:
        print(f"{'✓' if ok else '✗'} {label}")

    if "filter_season == '__all__'" not in routes:
        print()
        print("NOTE: If filter_season is '__all__', the route may be treating it as a real season.")
        print("That can cause choir filters to return zero rows because season_filter='__all__' matches nothing.")


def main():
    if not DB_PATH.exists():
        raise SystemExit(f"Could not find {DB_PATH}")

    show_counts()

    voicing, difficulty = pick_test_values()

    if not voicing:
        raise SystemExit("No usable choir voicing values found.")
    if not difficulty:
        raise SystemExit("No usable choir difficulty values found.")

    direct_sql_check(voicing, difficulty)
    rendered_route_check(voicing, difficulty)
    inspect_routes_source()

    print()
    print("Diagnostic complete.")


if __name__ == "__main__":
    main()
