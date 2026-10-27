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

if [ "$1" = "inspect" ]; then
  # `inspect --format {{.State.Pid}} <name>`: report the fixture PID so the
  # harness samples a real /proc fixture instead of this stub process.
  echo "inspect $*" >> "$LOG"
  echo "${DOCKER_STUB_PID:-1000}"
  exit 0
fi

exit 1
