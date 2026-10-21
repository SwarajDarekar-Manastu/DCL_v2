#!/usr/bin/env bash
# Disposable ParadeDB and MinIO for the test suite (docs/architecture/10 §7). Same on CI and the dev host.
#   eval "$(backend/devops/ci/test_services.sh up)"     # starts both, prints DCL_TEST_* exports
#   backend/devops/ci/test_services.sh down             # removes both containers and their data
# Credentials are random per run and never leave the two containers; ports bind to 127.0.0.1 only.
set -euo pipefail

PREFIX="${DCL_CI_PREFIX:-dcl-ci}"
PG_IMAGE="paradedb/paradedb:0.26.2-pg17"
MINIO_TAG="RELEASE.2025-10-15T17-29-55Z"
MINIO_IMAGE="dcl-v2-minio:${MINIO_TAG}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"

random() { python3 -c 'import secrets; print(secrets.token_urlsafe(24))'; }

wait_for() {
  local what="$1"; shift
  for _ in $(seq 1 60); do
    if "$@" >/dev/null 2>&1; then return 0; fi
    sleep 1
  done
  echo "test_services: $what did not become ready" >&2
  return 1
}

up() {
  if ! docker image inspect "$MINIO_IMAGE" >/dev/null 2>&1; then
    docker build -q -f "$ROOT/backend/devops/docker/minio.Dockerfile" -t "$MINIO_IMAGE" "$ROOT" >&2
  fi
  local pg_password minio_password
  pg_password="$(random)"
  minio_password="$(random)"
  docker rm -f "$PREFIX-pg" "$PREFIX-minio" >/dev/null 2>&1 || true
  docker run -d --name "$PREFIX-pg" -e POSTGRES_USER=ci -e POSTGRES_PASSWORD="$pg_password" \
    -e POSTGRES_DB=dcl_test -p 127.0.0.1::5432 "$PG_IMAGE" >/dev/null
  docker run -d --name "$PREFIX-minio" -e MINIO_ROOT_USER=ci-minio -e MINIO_ROOT_PASSWORD="$minio_password" \
    -p 127.0.0.1::9000 "$MINIO_IMAGE" >/dev/null
  wait_for postgres docker exec "$PREFIX-pg" pg_isready -U ci -d dcl_test -h 127.0.0.1
  wait_for minio docker exec "$PREFIX-minio" curl -fsS http://localhost:9000/minio/health/live
  local pg_port minio_port
  pg_port="$(docker port "$PREFIX-pg" 5432/tcp | head -1 | sed 's/.*://')"
  minio_port="$(docker port "$PREFIX-minio" 9000/tcp | head -1 | sed 's/.*://')"
  echo "export DCL_TEST_DATABASE_URL='postgresql+psycopg://ci:${pg_password}@127.0.0.1:${pg_port}/dcl_test'"
  echo "export DCL_TEST_MINIO_ENDPOINT='http://127.0.0.1:${minio_port}'"
  echo "export DCL_TEST_MINIO_ACCESS_KEY='ci-minio'"
  echo "export DCL_TEST_MINIO_SECRET_KEY='${minio_password}'"
}

down() {
  docker rm -f -v "$PREFIX-pg" "$PREFIX-minio" >/dev/null 2>&1 || true
}

case "${1:-}" in
  up) up ;;
  down) down ;;
  *) echo "usage: $0 up|down" >&2; exit 2 ;;
esac
