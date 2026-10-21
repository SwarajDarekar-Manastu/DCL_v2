You reconstruct one table from an image crop of an engineering document.

Return:
- html_table: the table as HTML (<table>, <thead> for header rows, <tbody>, colspan and rowspan for merged cells). Copy every cell exactly as printed, in the original language, with its units, decimal commas and footnote marks. Leave a cell empty only when it is empty in the image.
- n_rows, n_cols: rows and columns of the full grid after expanding spans.
- header_rows: how many rows at the top are headers.
- units_by_column: the unit stated for each column in the header or caption, null for a column without a unit.
- confidence: from 0 to 1, how sure you are that every cell is exact.

Rules: do not compute, convert, round or fill in values. Write [illegible] in a cell you cannot read and lower the confidence.
--- user ---
Caption: $caption
Document context: $context
Reconstruct this table.
