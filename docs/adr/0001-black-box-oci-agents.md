# Black-box agents behind an OCI contract

We evaluate complete coding-agent products as black boxes: every entrant ships an OCI image with a fixed entrypoint, and the harness only provisions the run, invokes that entrypoint and records the result. We rejected a fixed model harness because it would measure our scaffold rather than the agent, and rejected per-agent adapters because the benchmark would then own every integration; the cost is that every entrant must package its agent.
