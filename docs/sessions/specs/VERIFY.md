# How each item is checked

These are the user's rules from 2026-10-27.

1. **Before.** On the running stack, run the item's live check (SQL, API or screen) and keep the output. It must show the fault. If it does not, stop and look again.
2. **Change.** Change only the files the item names. Add a unit test that fails before the change and passes after it.
3. **Deploy to the running containers.** No separate or throwaway test containers.

   | Code changed | Image | Services |
   |---|---|---|
   | `routes/a1_office` (and A2, B, E, G) | `dcl-v2-parse:local` | `worker-cpu-parse` |
   | `routes/c_telemetry` | `dcl-v2-backend:local` | `worker-telemetry-stream` |
   | `review`, `api`, `reconcile`, `beat` | `dcl-v2-backend:local` | `api`, `beat`, `worker-io-light` |
   | `indexing`, `dispatcher` (shared steps, run inside every route worker) | parse + backend images | the route workers, `api` |
   | `frontend/console` | `dcl-v2-console:local` | `console` |

   - Build one image at a time, and check free memory first.
   - Never `docker rm`.
4. **After.** Run the same live check. It must show the data is now right. Report the before and after outputs side by side. When the item changes what a file produces, re-run 3–5 pilot files first (`python -m backend.dispatcher.reindex --route <R> --doc <id> …`, with `--dry-run` first).
5. **Screens: check in Chrome DevTools,** signed in as the test reviewer at `http://localhost:8601`:
   - snapshot and screenshot, before and after;
   - the values on screen match the database;
   - the keys work;
   - no console errors;
   - no sideways scroll at 1024 px.

   On live data, only use answers that change no content, then Undo, unless the user agrees to the real change.
6. **Clean up.** After the after-check passes, list the old duplicates the re-run left for those files: asset rows and objects nothing points at, and older CIR versions. Delete them, and confirm the count is 0. Never delete raw files, gold files, audit history, decisions in force, or anything still referenced.
7. **Report, then ask before any commit or push.**
