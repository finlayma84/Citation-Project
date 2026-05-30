# Word document formatting notes

The generated Word documents separate pastor-owned fields from Michael-owned music slots.

Pastor-owned lines are left blank and are intentionally ignored by sync/update:

- `OPENING HYMN:`
- `CLOSING HYMN:`

Michael-owned empty slots are generated as gray italic placeholders:

- `{PRELUDE}`
- `{MUSIC MINISTRY}`
- `{OFFERTORY}`
- `{POSTLUDE}`

When a slot is filled, it uses the pastor-facing label:

- `PRELUDE:`
- `MUSIC MINISTRY:`
- `OFFERTORY:`
- `POSTLUDE:`

The updater still recognizes old labels such as `MIN MUSIC:` and `OFFERING:` so older documents should continue syncing.

Version 3 adds Word pagination controls so each Sunday block stays together when possible. This prevents a date heading such as `SEP 27:` from appearing alone at the bottom of a page.

Calendar boundary rule: Eastertide includes Pentecost Sunday. The Season after Pentecost document begins with Trinity Sunday.
