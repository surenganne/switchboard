---
description: Suggest unused plugins and skills to turn off, with the context tokens each would save
---
Call the switchboard `hygiene` tool (pass `days` only if the user gave a window, 7–365; default 30).

- If `recording` is false: say usage logging is off, so there is nothing to judge, and that removing
  `"record_usage": false` from `~/.switchboard/settings.json` turns it back on.
- If `collecting` is true: say "`days_logged` of `window_days` days logged; suggestions start after `window_days`"
  in one line.
- Otherwise show a short table, biggest saving first: each entry of `plugins` (plugin key, skills count, ≈tokens)
  then each entry of `skills` (id, kind, path, ≈tokens). A plugin's `skills` count covers its skills, commands
  and agents; show its `mcp_servers` in their own column (or "—"). Then list `mostly_unused` as information only: plugin key,
  "used k of n" with the used ids, and the saving if the whole plugin were turned off. End with one line:
  "Skill list today ≈ `tokens_now` tokens; after these suggestions ≈ `tokens_after` (estimate; skills, commands and
  agents only, not MCP tools or hooks)." If every list is empty, say nothing went unused in the window.
  If `omitted` is present, say how many smaller suggestions were left out to keep the result short (the token
  totals still include them).

Always warn, next to the plugin list: turning a plugin off also removes its MCP servers (listed, but their
use is not tracked) and its hooks (not tracked), so check a plugin is not kept for those (a memory or context
tool, safety hooks) first.

Tell the user they can turn a plugin off with `/plugin` (or ask Claude to set it to false under `enabledPlugins`
in their settings), and remove or move a user/project skill's folder to drop it. Do not turn anything off yourself
unless they ask.
