"""Parquet conventions (file 05 §2): one directory per run UUID in ``dcl-telemetry``; row groups of
100k rows; ZSTD; field metadata ``unit, quantity, raw_name, raw_unit, conversion, sensor_tag``;
file metadata ``run_uuid, run_label, source_blob_sha256, parser_version, t0_*``."""

import json
from collections.abc import Iterable, Mapping
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

ROW_GROUP_ROWS = 100_000
COMPRESSION = "zstd"


def telemetry_key(run_uuid: str, name: str) -> str:
    return f"{run_uuid}/{name}.parquet"


def schema_with_metadata(
    schema: pa.Schema, field_metadata: Mapping[str, Mapping[str, str]], file_metadata: Mapping[str, object]
) -> pa.Schema:
    fields = [f.with_metadata({k: str(v) for k, v in field_metadata.get(f.name, {}).items()}) for f in schema]
    return pa.schema(
        fields, metadata={k: json.dumps(v) if not isinstance(v, str) else v for k, v in file_metadata.items()}
    )


def write_batches(path: Path, schema: pa.Schema, batches: Iterable[pa.RecordBatch]) -> int:
    """Write batches as row groups of ``ROW_GROUP_ROWS``; returns the number of rows."""
    rows = 0
    pending: list[pa.RecordBatch] = []
    pending_rows = 0
    with pq.ParquetWriter(path, schema, compression=COMPRESSION) as writer:
        for batch in batches:
            pending.append(batch.cast(schema) if batch.schema != schema else batch)
            pending_rows += batch.num_rows
            while pending_rows >= ROW_GROUP_ROWS:
                table = pa.Table.from_batches(pending, schema=schema)
                writer.write_table(table.slice(0, ROW_GROUP_ROWS), row_group_size=ROW_GROUP_ROWS)
                rest = table.slice(ROW_GROUP_ROWS)
                pending, pending_rows = rest.to_batches(), rest.num_rows
                rows += ROW_GROUP_ROWS
        if pending_rows:
            writer.write_table(pa.Table.from_batches(pending, schema=schema), row_group_size=ROW_GROUP_ROWS)
            rows += pending_rows
    return rows
