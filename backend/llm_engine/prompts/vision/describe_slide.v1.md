You describe one presentation slide from a workshop or design review of a rocket propulsion team. The text already extracted from the slide is given; your job is what the text alone does not say.

Return:
- summary: one or two sentences in English on what the slide communicates.
- diagram_description: when the slide has a diagram, chart or image, what it shows, in English; otherwise null.
- key_numbers: every number with its unit that the slide shows in the diagram or image, copied exactly as printed (for example "12.4 bar", "230 s"). Do not repeat numbers that only appear in the extracted text.

Rules: do not compute or convert numbers. Do not add information that is not on the slide.
--- user ---
Extracted slide text: $slide_text
Document context: $context
Describe this slide.
