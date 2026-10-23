# S6 — Routes (A2 LaTeX, B code, E diagrams, G archives and CAD)

Created 2026-10-23 by the user's build-out-first command. You own `backend/routes/{a2_source,b_code,e_diagrams,g_archives}` and their tests under `backend/tests/unit/routes/`. S1 owns the adapter registry (`backend/dispatcher/adapters.py`), the commit path and the schema; you send S1 (through the Lead) the one-line adapter registration for each route when it is ready.

Contract: every route returns the `ProcessedDocument` of `backend/dispatcher/contract.py`, exactly as Route A1 (`backend/routes/a1_office/route.py`) and Route C do. Read those two first, then the manual sections: file 03 §A2 (LaTeX masters, parts, PDF twins, bibliography, equations), §B (code: Tree-sitter, functions, docstrings, parameters with units, notebooks), §E (diagrams: draw.io, SVG, Visio, schematics via `read_schematic`), §G (archives: bomb guard, members as blobs, `.wbpz`, `.scdoc` as `cad_reference`, STL/STEP measured with trimesh), file 04 (chunking, anchors), file 06 (flags).

Test files: real ones from the allowlisted folders exported under `data/samples/` in S5's worktree (ask the Lead for a copy), public samples under `data/samples/web/` for formats the corpus lacks (S5 downloads them). One or two files per format are enough; edge cases from the manual are covered by synthetic fixtures.

Order: A2 (23 documents wait, including the TP12 report twin), B (4 code documents, 8 benchmark cases), E (2 diagrams), G (archives, wbpz, scdoc reference, STL/STEP adapter).

Rules: the sessions README applies in full (plan sheet, rubric, map page, own paths only for ruff, no secrets, messages to the Lead when blocked).
