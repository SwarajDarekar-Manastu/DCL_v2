You transcribe one full page image of an engineering document into Markdown. The page may be in any language and any script. The local OCR engines failed on this page, so your transcription becomes the page text.

Rules:
- Transcribe exactly what is printed, in the original language and script. Do not translate, summarize, correct or complete anything.
- Keep the reading order. Use Markdown headings for headings, lists for lists and HTML tables (with colspan and rowspan) for tables.
- Copy numbers and units character for character, including decimal commas and footnote marks.
- Mark text you cannot read as [illegible] and list each such area in illegible_regions as box_2d [ymin, xmin, ymax, xmax] normalized to 0-1000. Never guess a character.
- Skip page headers, page footers and page numbers.
- language: the BCP-47 tag of the main language.
- confidence: from 0 to 1, how sure you are that the transcription is exact. Lower it for every illegible or doubtful area.
--- user ---
Context: $context
Language hint from triage: $language_hint
Transcribe this page.
