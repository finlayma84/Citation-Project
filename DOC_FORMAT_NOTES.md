# Document formatting update

This version changes the generated Word document format so the pastor can add pastor-owned items manually.

## Generated Word documents now include

- `OPENING HYMN:` for pastor entry
- `{PRELUDE}` when no prelude is chosen yet
- `{MUSIC MINISTRY}` when no music ministry piece is chosen yet
- `{OFFERTORY}` when no offering/offertory piece is chosen yet
- `CLOSING HYMN:` for pastor entry
- `{POSTLUDE}` when no postlude is chosen yet

When a Michael-owned slot already has a selected piece, the generated document uses these display labels:

- `PRELUDE:`
- `MUSIC MINISTRY:`
- `OFFERTORY:`
- `POSTLUDE:`

## Sync behavior

The sync/update code recognizes both the new labels and the older labels:

- `MIN MUSIC:` still maps to Music Ministry
- `OFFERING:` still maps to Offertory
- `{PRELUDE}`, `{MUSIC MINISTRY}`, `{OFFERTORY}`, and `{POSTLUDE}` are replaceable placeholders

The sync/update code does not touch `OPENING HYMN:` or `CLOSING HYMN:`.

## Calendar boundary correction

Eastertide now runs through Pentecost Sunday. The Season after Pentecost document starts on Trinity Sunday.
