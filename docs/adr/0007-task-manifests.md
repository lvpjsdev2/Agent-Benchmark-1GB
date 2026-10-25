# Tasks ship as manifests, not images

A release contains only task manifests: the upstream repository URL, the pinned base commit, the issue, the dependency lockfile and the hidden tests. Setup builds the workspace locally; no prebuilt task images are published. We chose a small, transparent repository and reproducible builds over the fast start and fixed bytes of a registry; the cost is that setup needs network access and depends on the upstream commits staying available.
