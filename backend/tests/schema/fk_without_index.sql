-- Lists every foreign key in the current schema whose columns are not the leading columns
-- of a non-partial index (file 05 §3: "every FK column has an index"). CI fails on any row.
SELECT
    c.conrelid::regclass::text AS table_name,
    c.conname AS constraint_name,
    array_agg(a.attname ORDER BY k.ord)::text[] AS fk_columns
FROM pg_constraint AS c
CROSS JOIN LATERAL unnest(c.conkey) WITH ORDINALITY AS k(attnum, ord)
JOIN pg_attribute AS a ON a.attrelid = c.conrelid AND a.attnum = k.attnum
WHERE c.contype = 'f'
  AND c.connamespace = current_schema()::regnamespace
  AND NOT EXISTS (
      SELECT 1
      FROM pg_index AS i
      WHERE i.indrelid = c.conrelid
        AND i.indpred IS NULL
        AND (string_to_array(i.indkey::text, ' ')::int2[])[1:cardinality(c.conkey)] @> c.conkey
        AND c.conkey @> (string_to_array(i.indkey::text, ' ')::int2[])[1:cardinality(c.conkey)]
  )
GROUP BY c.conrelid, c.conname
ORDER BY 1, 2;
