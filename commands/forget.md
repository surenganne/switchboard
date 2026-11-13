---
description: Delete Switchboard's local record of which skills you picked
---
This deletes `~/.switchboard/choices.jsonl`, the local log of which skill you picked for which kind of task.
Profiles are kept.

First ask the user to confirm with AskUserQuestion (options: "Delete my choice history", "Keep it").
Only if they confirm, call the switchboard `forget` tool and report how many entries were removed.
To stop recording instead, tell them to put `{"record_choices": false}` in `~/.switchboard/settings.json`.
