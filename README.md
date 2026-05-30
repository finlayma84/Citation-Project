# Church Music Picker

Refactored Flask app for planning church service music.

## Run locally

```bash
cd "Citation Project Refactored"
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python app.py
```

The old one-file `app.py` has been split into a small Flask package:

- `app.py` / `run.py` — start the app
- `music_picker/routes.py` — web routes
- `music_picker/db.py` — SQLite connection handling
- `music_picker/calendar_utils.py` — Sunday/month/liturgical-season helpers
- `music_picker/services.py` — repertoire/history/search helpers
- `music_picker/documents.py` — Word document generation/sync wrappers
- `music_picker/templates/` — HTML templates moved out of Python strings
- `generate_doc.py`, `update_doc.py` — kept at project root because the app still uses them

## What was moved out of the active project root

One-off import, migration, cleanup, and diagnostic scripts are in `archive/one_off_scripts/`.
CSV/JSON import support files are in `archive/import_data/`.
Old database backups are in `archive/database_backups/`.

The archive is included so nothing is lost, but the active app root is much smaller.
