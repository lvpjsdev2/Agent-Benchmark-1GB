#!/bin/bash
# Docker CLI stub for ticket #20 tests (deterministic on macOS, no real docker).
#
# - `pull <image>`: logs and exits 0
# - `run <flags...> <image> <container command...>`: logs the full run args,
#   then execs the container command (all args after the first non-flag token,
#   the digest-pinned image)
# - everything else: exit 1
#
# Log lines are appended to $DOCKER_STUB_LOG (set by the test).
LOG="${DOCKER_STUB_LOG:?DOCKER_STUB_LOG must be set}"

if [ "$1" = "pull" ]; then
  echo "pull $2" >> "$LOG"
  exit 0
fi

if [ "$1" = "run" ]; then
  echo "run $*" >> "$LOG"
  shift
  # Skip docker flags (all start with --, harness composes them in = form)
  while [ $# -gt 0 ]; do
    case "$1" in
      --*) shift ;;
      *) break ;;
    esac
  done
  shift  # the image
  exec "$@"
fi

exit 1
