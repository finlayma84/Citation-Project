"""
Smoke tests for plan-view library add/update behavior.

Run:
    python test_plan_library_sync.py

This test temporarily modifies repertoire.db, then restores it from backup.
"""

from __future__ import annotations

import shutil
import sqlite3
import time
from pathlib import Path

from music_picker import create_app


DB_PATH = Path("repertoire.db")
BACKUP_PATH = Path(f"repertoire_test_backup_{int(time.time())}.db")

TEST_ISO = "2031-01-05"


def connect():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    return con


def assert_true(condition, message):
    if not condition:
        raise AssertionError(message)


def get_one(sql, params=()):
    with connect() as con:
        return con.execute(sql, params).fetchone()


def get_count(sql, params=()):
    row = get_one(sql, params)
    return row[0] if row else 0


def post_plan(client, data):
    response = client.post(f"/plan/{TEST_ISO}", data=data, follow_redirects=False)
    assert_true(
        response.status_code in (302, 303),
        f"Expected redirect after save, got {response.status_code}: {response.get_data(as_text=True)[:500]}",
    )


def base_form():
    """Provide all slot fields so plan() can safely loop through SLOTS."""
    form = {
        "date": TEST_ISO,
        "season": "Epiphany",
        "occasion": "Test Occasion",
    }

    for slot in ["Prelude", "Min Music", "Offering", "Postlude"]:
        form[f"title_{slot}"] = ""
        form[f"composer_{slot}"] = ""
        form[f"composer_dates_{slot}"] = ""
        form[f"performer_{slot}"] = "Unspecified"
        form[f"source_type_{slot}"] = ""
        form[f"source_id_{slot}"] = ""
        form[f"library_target_{slot}"] = "personal"

    return form


def test_manual_personal_entry(client):
    title = "ZZZ Test Manual Personal Piece"
    composer = "Test Composer"
    dates = "1900-1999"

    form = base_form()
    form.update({
        "title_Prelude": title,
        "composer_Prelude": composer,
        "composer_dates_Prelude": dates,
        "performer_Prelude": "Michael",
        "add_to_library_Prelude": "1",
        "library_target_Prelude": "personal",
    })

    post_plan(client, form)

    scheduled = get_one("""
        SELECT * FROM pieces
        WHERE title=?
          AND composer=?
          AND library_only=0
          AND slot='Prelude'
          AND source_type='personal'
    """, (title, composer))

    library = get_one("""
        SELECT * FROM pieces
        WHERE title=?
          AND composer=?
          AND composer_dates=?
          AND library_only=1
          AND chosen_by='Michael'
    """, (title, composer, dates))

    assert_true(scheduled is not None, "Manual personal entry was not saved as scheduled piece.")
    assert_true(library is not None, "Manual personal entry was not added to personal library.")
    print("✓ Manual personal entry creates/updates personal library item")


def test_manual_choir_entry(client):
    title = "ZZZ Test Manual Choir Piece"
    composer = "Choir Composer"

    form = base_form()
    form.update({
        "title_Min Music": title,
        "composer_Min Music": composer,
        "performer_Min Music": "Chancel Choir",
        "add_to_library_Min Music": "1",
        "library_target_Min Music": "choir",
    })

    post_plan(client, form)

    scheduled = get_one("""
        SELECT * FROM pieces
        WHERE title=?
          AND composer=?
          AND library_only=0
          AND slot='Min Music'
          AND source_type='choir'
    """, (title, composer))

    library = get_one("""
        SELECT * FROM choir_library
        WHERE title=?
          AND composer=?
          AND active=1
    """, (title, composer))

    assert_true(scheduled is not None, "Manual choir entry was not saved as scheduled piece.")
    assert_true(library is not None, "Manual choir entry was not added to choir_library.")
    print("✓ Manual choir entry creates/updates choir_library item")


def test_manual_bell_entry(client):
    title = "ZZZ Test Manual Bell Piece"
    composer = "Bell Arranger"

    form = base_form()
    form.update({
        "title_Offering": title,
        "composer_Offering": composer,
        "performer_Offering": "Handbells",
        "add_to_library_Offering": "1",
        "library_target_Offering": "bells",
    })

    post_plan(client, form)

    scheduled = get_one("""
        SELECT * FROM pieces
        WHERE title=?
          AND composer=?
          AND library_only=0
          AND slot='Offering'
          AND source_type='bells'
    """, (title, composer))

    library = get_one("""
        SELECT * FROM bell_library
        WHERE title=?
          AND composer_arranger=?
          AND active=1
    """, (title, composer))

    assert_true(scheduled is not None, "Manual bell entry was not saved as scheduled piece.")
    assert_true(library is not None, "Manual bell entry was not added to bell_library.")
    print("✓ Manual bell entry creates/updates bell_library item")


def test_existing_choir_source_update(client):
    original_title = "ZZZ Test Existing Choir Source"
    updated_title = "ZZZ Test Existing Choir Source Corrected"
    original_composer = "Original Choir Composer"
    updated_composer = "Corrected Choir Composer"

    with connect() as con:
        cur = con.cursor()
        cur.execute("""
            INSERT INTO choir_library (
                title, composer, season, season_filter, occasion_filter, active
            )
            VALUES (?, ?, 'General', 'Pentecost', '', 1)
        """, (original_title, original_composer))
        source_id = cur.lastrowid
        con.commit()

    form = base_form()
    form.update({
        "title_Postlude": updated_title,
        "composer_Postlude": updated_composer,
        "performer_Postlude": "Chancel Choir",
        "source_type_Postlude": "choir",
        "source_id_Postlude": str(source_id),
        "add_to_library_Postlude": "1",
        "library_target_Postlude": "choir",
    })

    post_plan(client, form)

    updated_source = get_one("""
        SELECT * FROM choir_library
        WHERE id=?
          AND title=?
          AND composer=?
          AND active=1
    """, (source_id, updated_title, updated_composer))

    scheduled = get_one("""
        SELECT * FROM pieces
        WHERE title=?
          AND composer=?
          AND slot='Postlude'
          AND source_type='choir'
          AND source_id=?
          AND library_only=0
    """, (updated_title, updated_composer, source_id))

    assert_true(updated_source is not None, "Existing choir source was not updated.")
    assert_true(scheduled is not None, "Scheduled row did not preserve choir source_type/source_id.")
    print("✓ Existing choir source updates source library record and preserves source metadata")


def main():
    assert_true(DB_PATH.exists(), f"Could not find {DB_PATH}")

    print(f"Backing up {DB_PATH} → {BACKUP_PATH}")
    shutil.copy2(DB_PATH, BACKUP_PATH)

    try:
        app = create_app()
        app.config.update(TESTING=True)

        with app.test_client() as client:
            test_manual_personal_entry(client)
            test_manual_choir_entry(client)
            test_manual_bell_entry(client)
            test_existing_choir_source_update(client)

        print()
        print("All plan/library sync smoke tests passed.")

    finally:
        print()
        print(f"Restoring original database from {BACKUP_PATH}")
        shutil.copy2(BACKUP_PATH, DB_PATH)
        BACKUP_PATH.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
