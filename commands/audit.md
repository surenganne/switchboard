---
description: List task types where you keep passing over Switchboard's top pick
---
Call the switchboard `audit` tool. For each group it returns, say in one line: the task type (category,
targets, focus), how many times the top pick was passed over, and which skills were chosen instead. Suggest
re-profiling the skills involved (`/switchboard:profile`) if their profiles look wrong. If there are no
groups, say so in one line.
