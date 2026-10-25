# The 1 GB envelope bounds disk, not memory

A run must fit its image, dependencies, workspace and artifacts within 1 GB of disk; RAM is a separate budget. We chose disk because the benchmark's defining constraint is how large an environment an agent can carry, and because disk and memory are different failure modes that a single combined number would blur. The alternative readings of "1 GB" — model weights, or the task repository — were rejected because they size the inputs rather than the agent's operating envelope.
