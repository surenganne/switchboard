---
description: Show how many skills Switchboard knows, how many are profiled, and which task areas overlap
---
Call the switchboard `status` tool. Report plainly in a few lines: total entries with the split from `by_kind`
(skills, commands, agents), profiled, waiting to be profiled, and the task areas (categories) where two or more
profiled entries overlap. Under each overlapping area, list its entries from `overlap_skills` by id. If entries are waiting, mention `/switchboard:profile`.
