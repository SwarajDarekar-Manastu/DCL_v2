---
name: Visual lookup
description: Photos, plots, video frames and diagram renders, shown in the chat.
intents: [visual_lookup]
dcl-playbook: visual_lookup
tools: [inspect_visuals, search_documents]
---

# Visual lookup

Photos, plots, video frames and diagram renders, shown in the chat.

## When to use

"Show me the burned injector mesh photos", "Is the catalyst screen visibly deformed after T04?"

## What the engine does

1. Search photos, figures, video frames and diagram renders, filtered by test plan and component.
2. For a question about what is visible, send the top four images back to the vision model with your question; that answer is an observation made now, not part of the indexed record, and is marked as such.
3. Search the text of the readings and the reports around them, preferring photo, figure and video pieces.
4. Show the images as a strip of thumbnails with links.

## Tools

`inspect_visuals`, `search_documents`

## Limits

- Image links expire after 15 minutes.

Every number in the answer comes from a tool result and is checked before it is shown; each cited source carries its provenance label.
