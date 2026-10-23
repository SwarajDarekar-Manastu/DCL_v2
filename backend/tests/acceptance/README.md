# Milestone acceptance checks (owner: S5, feature `quality/acceptance`)

One checklist per milestone of `docs/architecture/10_development_plan.md` §5. Each accept
criterion is either an automated check (pytest, pass/fail) or a written procedure with a
verification command; `M<n>.md` maps every criterion to one of the two.

- `M<n>.md`: the checklist for milestone n.
- `m<n>_state.py`: read-only queries shared by the tests and the snapshot CLI.
- `test_m<n>_acceptance.py`: checks against the live stack database. Skipped unless enabled:

  ```bash
  DCL_ACCEPTANCE=1 DCL_DATABASE_URL=<stack db> uv run pytest backend/tests/acceptance
  ```

  The session sets `default_transaction_read_only`; a check can never write. Checks that read
  MinIO (M2 Parquet) take `DCL_MINIO_ENDPOINT`, `DCL_MINIO_ACCESS_KEY`, `DCL_MINIO_SECRET_KEY` and
  only GET; without them those checks are skipped.
- `test_m<n>_checks_on_seeded_db.py`: proves each check passes on a good state and fails on a
  bad one, on a disposable database (`DCL_TEST_DATABASE_URL`, like the schema tests).

- `test_format_routes.py` (`FORMATS.md`): route-level checks over the public format samples in
  `data/samples/web/`; local only, no stack: `uv run --group parse pytest backend/tests/acceptance/test_format_routes.py`.
