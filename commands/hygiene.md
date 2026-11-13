---
description: Suggest unused plugins and skills to turn off, with the context tokens each would save
---
Call the switchboard `hygiene` tool (pass `days` only if the user gave a window, 7–365; default 30).

- If `recording` is false: say usage logging is off, so there is nothing to judge, and that removing
  `"record_usage": false` from `~/.switchboard/settings.json` turns it back on.
- If `collecting` is true: say "`days_logged` of `window_days` days logged; suggestions start after `window_days`"
  in one line.
- Otherwise show a short table, biggest saving first: each entry of `plugins` (plugin key, skills count, ≈tokens)
  then each entry of `skills` (id, path, ≈tokens). Then list `mostly_unused` as information only: plugin key,
  "used k of n" with the used ids, and the saving if the whole plugin were turned off. End with one line:
  "Skill list today ≈ `tokens_now` tokens; after these suggestions ≈ `tokens_after` (estimate; skills and commands
  only, not agents, MCP tools or hooks)." If every list is empty, say nothing went unused in the window.

Tell the user they can turn a plugin off with `/plugin` (or ask Claude to set it to false under `enabledPlugins`
in their settings), and remove or move a user/project skill's folder to drop it. Do not turn anything off yourself
unless they ask.
