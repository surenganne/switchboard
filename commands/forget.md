---
description: Delete Switchboard's local record of which skills you picked and used
---
This deletes `~/.switchboard/choices.jsonl` (which skill you picked for which kind of task) and
`~/.switchboard/usage.jsonl` with `first_seen.json` (which skills you used, for `/switchboard:hygiene`). Deleting the
usage log restarts the 30-day hygiene window. Profiles are kept.

First ask the user to confirm with AskUserQuestion (options: "Delete my history", "Keep it").
Only if they confirm, call the switchboard `forget` tool with `confirm: true` and report how many choice and usage
entries were removed.
To stop recording instead, tell them to put `{"record_choices": false}` and/or `{"record_usage": false}` in
`~/.switchboard/settings.json`.
