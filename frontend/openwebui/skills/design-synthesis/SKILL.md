---
name: Design synthesis and trade study
description: Candidate designs against requirements, with a provenance label on every value.
intents: [design_synthesis]
dcl-playbook: design_synthesis
tools: [external_search, physics_calculator, search_documents]
---

# Design synthesis and trade study

Candidate designs against requirements, with a provenance label on every value.

## When to use

"15 N green thruster, Isp above 230 s, below 20 W preheat, 1U: what are our options?"

## What the engine does

1. Break the request into constraints.
2. Search our internal baselines (reports, catalyst tables, runs).
3. Search the kept library (datasheets, papers) for components and published results.
4. Check each candidate with the physics calculator.
5. Search the web only for gaps the internal material and the library do not cover, with a sanitized query that contains no internal names or values, and only for users in the allowed group.
6. Answer with a trade matrix; each cell is labelled measured, internal report, vendor claim, literature or web.

## Tools

`external_search`, `physics_calculator`, `search_documents`

## Limits

- Web search can be turned off by the administrator and is never used for facts about our own hardware, tests or documents.

Every number in the answer comes from a tool result and is checked before it is shown; each cited source carries its provenance label.
