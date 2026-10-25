# One fixed model per release

Every baseline agent in a release runs on the same fixed model, so score differences reflect the agent rather than the model. We rejected per-agent default models because they confound the comparison, and two models because they double the run matrix before the benchmark has a stable task set. The cost is that a release's ranking is conditional on one model, which the results table must state.
