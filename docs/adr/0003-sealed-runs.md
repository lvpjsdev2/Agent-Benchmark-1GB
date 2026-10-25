# Runs are sealed except for the model gateway

Agents run without general network access: every dependency a task needs must already be in the image, and the only egress is the harness-owned model gateway. We chose sealed runs because a benchmark that can download its way out of a problem is neither reproducible nor contamination-resistant; the cost is that tasks requiring a new package are out of scope. Allowing an allowlisted registry was rejected because package resolution is non-deterministic and still leaves a channel for fetching solutions.
