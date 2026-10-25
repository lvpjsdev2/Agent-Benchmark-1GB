# The 1 GB envelope is the niche, not another SWE-bench

This benchmark compares lightweight Claw-style agents on Python repository tasks, and its defining constraint is that a run's image, dependencies, workspace and artifacts fit in 1 GB of disk. Claw-SWE-Bench already covers 350 real issues across eight languages without a disk envelope; repeating that shape would add little. We keep the task set Python-only and public so the envelope, not language breadth, is the variable under test.
