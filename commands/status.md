---
description: Show how many skills Switchboard knows, how many are profiled, and which task areas overlap
---
Call the switchboard `status` tool. Report plainly in a few lines: total entries with the split from `by_kind`
(skills, commands, agents), profiled, waiting to be profiled, and the task areas (categories) where two or more
profiled entries overlap. If entries are waiting, mention `/switchboard:profile`. If `shadowed` is not empty, say
those ids hide an agent of the same name from routing.
