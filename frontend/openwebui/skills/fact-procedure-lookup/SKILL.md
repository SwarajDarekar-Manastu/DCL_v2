---
name: Fact and procedure lookup
description: A stated fact or a procedure, found in the documents and cited by page.
intents: [fact_lookup, procedure_lookup]
tools: [search_documents]
---

# Fact and procedure lookup

A stated fact or a procedure, found in the documents and cited by page.

## When to use

"What is the pre-firing checklist for Injector 14?", "Which catalyst was used in TP12?"

## What the engine does

1. Search the indexed documents (hybrid: keywords and meaning), filtered by document kind when the question implies one (procedures, test plans, calibrations).
2. Read the surrounding section of the best passages.
3. Answer only from the passages, with a page citation for every statement.

## Tools

`search_documents`

## Limits

- If the documents do not say it, the answer says that the evidence is insufficient instead of guessing.

Every number in the answer comes from a tool result and is checked before it is shown; each cited source carries its provenance label.
