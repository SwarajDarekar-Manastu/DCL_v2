# Plan: platform/compose-stack — RustFS adoption step 2 (lifecycle watch), open

| Field | Value |
|-------|-------|
| Feature | `platform/compose-stack` |
| Session | S4 |
| Branch | claude/gifted-hofstadter-0bec1c |
| Opened | 2026-10-22 |
| Delete when | the check below exits 0 after 2026-10-24 00:00Z and the result is in `object_store_evaluation.md` |

## Intent

Step 3 is done (commit on this branch). Step 2 is waiting on time: the watch store `dcl-s4-rustfs-watch` was seeded 2026-10-22 07:53Z.

## Steps left

1. After 2026-10-24 00:00Z: `uv run python backend/devops/ci/lifecycle_watch.py check --endpoint http://127.0.0.1:9293 --access-key s4watch --secret-key <from docker inspect>`
2. Record the per-case result in `object_store_evaluation.md` step 2 and the map change log; remove the watch container and volume.
3. Delete this sheet; STATUS; merge request (auth check f7fdefb + step 3 + step 2).

## Rubric

- [ ] the three 1-day cases cleared, the three controls intact (exit 0)
- [x] step 3 load test (0 errors, both stores, two runs)
