# Agent Benchmark 1GB

A public benchmark that runs lightweight agents on Python repository tasks inside a 1 GB disk envelope and turns each run into a reproducible, comparable score.

## Language

**Benchmark**:
The complete evaluation this repo ships: the tasks, the harness that executes agents, and the scoring that makes runs comparable.
_Avoid_: Eval, test suite, evaluation framework

**Agent**:
A complete agent product or scaffold that owns its own loop and tools, evaluated on coding tasks as a black box.
_Avoid_: Assistant, copilot, bot

**Task**:
A seeded repository paired with an issue drawn from a real merged PR with tests; the agent edits the code and hidden tests decide whether the run succeeded.
_Avoid_: Problem, instance, case

**Task set**:
The public tasks shipped in one release; drawn from permissively licensed repositories, with no private holdout and no rotation within a version.
_Avoid_: Dataset, suite

**Task manifest**:
The pinned commit, issue, dependency lockfile and hidden-test reference that define a task; setup builds its workspace from the manifest.
_Avoid_: Spec, config

**Setup**:
The pre-run step that builds a task workspace from its manifest; setup may use the network, while the run it feeds is sealed.
_Avoid_: Bootstrap, install

**Gold patch**:
The merged PR's code change, used to derive the task; the agent never sees it.
_Avoid_: Solution, reference answer

**Hidden tests**:
The task's acceptance tests, withheld from the agent; they decide whether the task passed.
_Avoid_: Checks

**Pass@1**:
The share of tasks an agent solves on a single attempt; a task counts only when all hidden tests pass and the envelope is respected.
_Avoid_: Accuracy, success rate

**Run**:
One execution of one agent on one task, bounded by the envelope, the memory budget and the time budget.
_Avoid_: Trial, episode, attempt

**Time budget**:
The maximum wall-clock time for a run; exceeding it fails the run.
_Avoid_: Timeout, limit

**Memory budget**:
The 4 GB RAM limit for a run, separate from the 1 GB disk envelope.
_Avoid_: RAM limit

**Harness**:
The repo-owned runner that provisions a run, invokes the agent and records the outcome, without implementing the agent's loop.
_Avoid_: Framework

**Driver**:
The agent-owned part of the image entrypoint that starts the agent, feeds it the task and exits when the run is complete.
_Avoid_: Adapter, wrapper

**Agent image**:
The OCI image that packages an agent and its driver for the benchmark.
_Avoid_: Container, submission

**Workspace contract**:
The harness/agent interface: the agent edits a mounted copy of the task repository and its final diff is the answer.
_Avoid_: Protocol, API

**Benchmark model**:
The single fixed model every baseline agent uses in a release, so scores compare agents rather than models.
_Avoid_: Default model

**Model gateway**:
The harness-owned proxy that is the only network egress from a run; it forwards requests to the benchmark model and records token use.
_Avoid_: Proxy, API

**Envelope**:
The 1 GB disk budget for a run: its image, dependencies, workspace and produced artifacts together. RAM is bounded separately by the memory budget.
_Avoid_: Limit, quota
