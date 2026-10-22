# M9 pilot walk-through (Open WebUI acceptance)

| Field | Value |
|-------|-------|
| Purpose | Step-by-step script a pilot engineer follows to accept M9 |
| Owner session | S3 |
| Spec | docs/architecture/10_development_plan.md §5 M9; 08 §2, §6 |
| Features covered | `frontend/openwebui-pipe`, `frontend/openwebui-actions-skills`, `frontend/viewer`, `frontend/console-shell-auth` |
| Last updated | 2026-10-22 |

M9 is accepted when four things hold (file 10 §5): pilot engineers work only in Open WebUI; citations open the viewer at the right page even after a re-index; "Show trace" renders; feedback lands on `answer_traces`. This page turns each one into steps and a pass condition. An engineer runs it in a browser. Steps marked **(operator)** need someone with shell access to the stack host.

## Before you start (operator)

| # | Condition | How to confirm |
|---|-----------|----------------|
| P1 | Open WebUI runs on the stack (M9 container, S4) | `http://<host>:8300` shows the sign-in page |
| P2 | Both functions are installed and switched on | `frontend/openwebui/README.md` steps 1–5; the install script prints "updated" or "created" for `manastu_engine` and `manastu_actions` |
| P3 | The Answer Engine answers (M8) | `POST /v1/answer` returns a stream, not 501 |
| P4 | The Console signs in with Entra ID | the Console container on port 8601 with `VITE_ENTRA_*` set; `DCL_CONSOLE_BASE_URL` points at it (DECISIONS 2026-10-22: the dev sign-in on 8600 is not used for acceptance) |
| P5 | Engineers are in the group that sees "Manastu Propulsion Engine" | Admin Panel › Models › visibility |
| P6 | At least one indexed document has a known page to cite | pick one from the TP7 or Injector 14 folders; write down file name and page |

## 1. Work only in Open WebUI

1. Sign in to Open WebUI with your Manastu account.
2. Pick **Manastu Propulsion Engine** in the model menu.
3. Ask a question whose answer you know, for example the peak chamber pressure of a test you ran. Use your normal wording.
4. While it answers, the status line above the reply shows the steps (searching, reading telemetry, checking numbers).
5. Attach a small file (a photo or a PDF under 25 MB) and ask about it.

Pass when: the answer arrives with numbered citations; no step needed another tool; the attachment was used or a notification said why it was skipped. A plain Gemini chat (the other model) still works for non-DCL questions.

## 2. Citations open the right page

1. Under the answer, open each source. Each one is a link to the Console viewer (`/docs/{id}/viewer?anchor=…`).
2. The first time, the Console asks you to sign in, then returns to the same link.
3. Check that the page shown is the page the answer cites. The cited passage has a box drawn around it.
4. For a non-English source, use the **Translate** toggle in the viewer.

Pass when: every citation opens the cited page with the box on the cited passage, or the viewer says plainly that it fell back to the page.

### 2a. After a re-index (operator, then engineer)

1. Keep the chat from step 1 open. Write down two citation links.
2. **(operator)** Re-index those documents (a new chunk size or a forced re-process; S1/S2 command at the time of M9).
3. Open the same two links again from the old chat.

Pass when: each link opens the same page. If the passage text changed, the viewer shows "The cited passage changed since it was cited; showing the page it was on." and still opens the page. A blank page or an error fails this check.

## 3. "Show trace" renders

1. Under an engine answer, click **Show trace**.

Pass when: a panel opens inside the chat with the tool calls, the retrieved passages (each with a viewer link), the claims and the verifier's verdicts. Under a plain Gemini answer the button does not appear.

## 4. Feedback lands on `answer_traces`

1. Under an answer, click **Report issue**.
2. Type a reason number and a comment, for example `4 the unit should be psia`. The reasons are 1 wrong number, 2 wrong citation, 3 missing document, 4 wrong unit or extraction, 5 wrong translation.
3. Click thumbs-up on another answer that has a correct number, then **Add to benchmark** and keep the default suite `from-chat`.
4. **(operator)** Confirm both arrived:

```sql
select trace_id, feedback from answer_traces order by created_at desc limit 5;
select case_id, status, source_trace_id from benchmark_cases where suite = 'from-chat' order by created_at desc limit 5;
```

Pass when: the report shows in `answer_traces.feedback` with kind `wrong_unit` and your comment; a `wrong_unit` report also opened a SOFT `CONFLICT` case in the Review queue; the benchmark case is a `draft` with the chat's trace id, and a reviewer can approve it in Console › Benchmark.

Cancel check: start **Report issue** again and cancel. Nothing new appears in `answer_traces.feedback`.

## Record the result

Write one line per check (1, 2, 2a, 3, 4) with pass or fail, the date, the engineer and, for a failure, the chat link and a screenshot. Hand it to S5 for `backend/tests/acceptance/M9.md`.

## Known gaps at the time of writing

- Open WebUI is not running yet (M9 container, S4) and the engine answers 501 until M8. Steps 1–4 cannot run before both.
- Entra ID is not registered, so P4 is open; the dev sign-in does not count for acceptance.
- `answer_traces` arrives with M8 (S2); the SQL in step 4 assumes its `feedback` column.
- The Filter function is deferred (Lead decision); policy is applied by the engine from the signed groups, so no step checks it.

## Related

- `frontend/openwebui-pipe`, `frontend/openwebui-actions-skills`, `frontend/viewer`, `frontend/console-shell-auth`
- `quality/acceptance` (S5 owns the checklist files)
