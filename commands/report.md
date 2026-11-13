---
description: Build a local HTML report of your Switchboard activity (picks over time, most-chosen skills, profiling coverage)
---
Call the switchboard `report` tool. It writes `~/.switchboard/report.html` on this machine and returns its path,
the number of installed skills and the number of picks recorded.

Tell the user in two or three lines: where the file is, how many picks and skills it covers, and that they can
open it with `open <path>` (macOS) or `xdg-open <path>` (Linux). If there are no picks yet, say the activity
sections fill in once Switchboard has offered them a choice and they picked a skill. Do not open the file
yourself unless they ask.
