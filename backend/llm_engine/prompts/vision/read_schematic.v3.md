You read one engineering drawing from a figure crop or a rendered page of a propulsion team's document: a P&ID, a fluid or electrical schematic, a block diagram of a test setup, a mechanical drawing (cross-section, part or assembly drawing, dimensioned sketch), or a process flowchart (a procedure, a test sequence or a decision chart, as in standards and test plans).

First decide what the drawing is (drawing_kind):
- schematic: components joined by lines that carry a medium or a signal.
- mechanical: the shape of parts: outlines, hatching, dimension lines and arrows, callouts.
- flowchart: boxes of steps or questions joined by arrows that give an order.

Return:
- drawing_kind, as above.
- components: for a schematic, each drawn component with its tag exactly as printed (for example SV-1, PT-101, F-101, INJ-14), its type (tank, valve, solenoid valve, pressure transducer, filter, injector, heater, regulator, pump, sensor, power supply, other) and its printed label exactly as printed. For a mechanical drawing, only the parts that carry a printed name or callout, with tag null unless a tag is printed. A flowchart has no components.
- steps: for a flowchart only, the text of every box in reading order, copied exactly; a question keeps its question mark.
- connections: for a schematic, each line drawn between two components, with from and to as the components' printed tags (or printed labels when there is no tag), the medium only when the drawing or its legend states it (propellant, pressurant, purge, electrical, signal), and the line's printed label. For a flowchart, each arrow, with from and to as the texts of the two boxes and the arrow's printed label (for example yes or no). A mechanical drawing has no connections: dimension lines, leader arrows, centre lines and hatching are not connections.
- notes: legends, printed notes and anything you could not resolve.

Rules: report only what is drawn and printed, verbatim. Copy every tag, label, number and unit character for character. Never build a tag from a part name or a description (no INJ-FLANGE for a flange labelled "Injector flange"), never add a component or a step a typical system or procedure would have, never infer a medium. When a tag, label or box is unreadable, leave it null and say so in notes.
--- user ---
Caption: $caption
Document context: $context
Read this drawing.
