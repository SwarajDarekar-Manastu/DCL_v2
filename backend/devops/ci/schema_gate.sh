#!/usr/bin/env bash
# Schema gate (docs/architecture/05 §3, 10 §7): migrations apply, autogenerate finds no drift, and every
# foreign key has a leading index. Needs DCL_TEST_DATABASE_URL pointing at an empty disposable database.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
: "${DCL_TEST_DATABASE_URL:?DCL_TEST_DATABASE_URL must point at a disposable database}"
export DCL_DATABASE_URL="$DCL_TEST_DATABASE_URL"
cd "$ROOT"

uv run alembic -c backend/postgres/alembic.ini upgrade head
uv run alembic -c backend/postgres/alembic.ini check

uv run python - <<'PY'
import os
from pathlib import Path

from sqlalchemy import create_engine, text

from backend.postgres.session import normalize_url

sql = Path("backend/tests/schema/fk_without_index.sql").read_text()
with create_engine(normalize_url(os.environ["DCL_DATABASE_URL"])).connect() as conn:
    rows = conn.execute(text(sql)).fetchall()
for row in rows:
    print(f"FK without leading index: {row.table_name}.{row.constraint_name} {row.fk_columns}")
if rows:
    raise SystemExit(f"schema gate: {len(rows)} foreign key(s) without an index")
print("schema gate: migrations at head, no drift, every foreign key indexed")
PY
