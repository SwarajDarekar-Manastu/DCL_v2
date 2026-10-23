# asset

Images that ship with the product, committed to the repository. Nothing secret and nothing from a customer: test data only.

| Folder | Used by | What it holds |
|--------|---------|---------------|
| `rules-guide/` | the "How rules work" guide on the Console's Rules page (`frontend/console/src/lib/components/review/rules_guide.ts`) | Screenshots of the real Console on the test corpus, numbered in reading order |

The Console imports these through the `$asset` alias (`svelte.config.js`), so Vite hashes and caches them. The Console image gets the folder through the Compose build context `asset` (see `backend/devops/compose.yaml`).

To refresh a screenshot: open the screen it shows in the Console on test data at 1440 × 900, save a PNG under the same name, and run `npm test` in `frontend/console`. Keep the number prefix; the guide's steps name the files.
