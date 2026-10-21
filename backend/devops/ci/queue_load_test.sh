#!/usr/bin/env bash
# M1 queue load test against a running compose project (docs/architecture/10 §5 M1).
#   backend/devops/ci/queue_load_test.sh [--project dcl-v2] [load_test.py options, e.g. --tasks 5000]
# Runs backend.celery_redis.load_test inside the project, then checks containment at the container level:
# no worker container restarted, and worker processes were killed only in worker-telemetry-stream.
set -euo pipefail

PROJECT="dcl-v2"
if [[ "${1:-}" == "--project" ]]; then PROJECT="$2"; shift 2; fi
RUNNER="${DCL_LOAD_TEST_SERVICE:-worker-io-light}"
WORKERS=(worker-io-light worker-cpu-parse worker-telemetry-stream worker-media worker-vision-batch worker-embed)

state() { docker inspect --format '{{.State.StartedAt}} restarts={{.RestartCount}}' "${PROJECT}-$1-1"; }

declare -A before
for w in "${WORKERS[@]}"; do before[$w]="$(state "$w")"; done
since="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

status=0
docker compose -p "$PROJECT" exec -T "$RUNNER" python -m backend.celery_redis.load_test "$@" || status=$?

echo "containment:"
for w in "${WORKERS[@]}"; do
  kills="$(docker logs --since "$since" "${PROJECT}-${w}-1" 2>&1 | grep -c 'signal 9 (SIGKILL)' || true)"
  restarted="no"
  [[ "$(state "$w")" == "${before[$w]}" ]] || restarted="yes"
  echo "  $w: worker processes killed=$kills, container restarted=$restarted"
  if [[ "$restarted" == "yes" ]]; then status=1; fi
  if [[ "$w" != "worker-telemetry-stream" && "$kills" != "0" ]]; then status=1; fi
done
[[ $status -eq 0 ]] && echo "QUEUE LOAD TEST PASSED" || echo "QUEUE LOAD TEST FAILED"
exit $status
