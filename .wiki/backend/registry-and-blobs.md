# Registry, content-addressed blobs, downloader

| Field | Value |
|-------|-------|
| Feature id | `backend/registry-and-blobs` |
| Status | in-progress |
| Owner session | S1 |
| Spec | docs/architecture/02_phase1_ingestion_sync.md §5–§7; 05_storage_schema.md §4.1 |
| Last updated | 2026-10-21 |

## Purpose

Download accepted items into MinIO keyed by SHA-256, verify quickXorHash, deduplicate by (quick_xor_hash,size), and maintain drive_items/drive_folders/blobs/blob_derivations.

## Location

Code:
- `backend/sync/downloader.py` (`land_item()`: zero-download link by (quickXorHash, size), 302 target fetched without the token, one-pass SHA-256 + quickXorHash, verify, server-side copy to the content address, conflict-safe blob insert, item LANDED)
- `backend/postgres/models/registry.py` (M1 tables, done with backend/schema-and-migrations)
- `backend/sync/export_blobs.py` (read-only export of landed blobs of folder subtrees; CLI)
- `backend/storage/minio.py` (client from `Group.MINIO`, `BucketStore.get/put`, `presign_get` 15 min, `ensure_buckets`, `raw_key`, `uri`/`parse_uri`)

Tests and fixtures:
- `backend/tests/unit/storage/test_minio.py` (server tests need `DCL_TEST_MINIO_ENDPOINT` on a disposable MinIO)
- `backend/tests/unit/sync/test_downloader.py`, `backend/tests/unit/sync/test_export_blobs.py` (server tests need `DCL_TEST_DATABASE_URL` + `DCL_TEST_MINIO_ENDPOINT`)
- `backend/tests/integration/registry/`

## Interfaces

Provides:
- `BucketStore(client, "dcl-cir").get(key) -> bytes | None` / `.put(key, data, content_type, metadata) -> s3 URI` (S2 vision cache, staged payloads)
- `presign_get(client, minio_uri)` (S3 viewer and assets; the caller checks the session)
- blobs rows
- location→blob links
- jobs idempotency keys: `Job.key_for(stage, parser_version, pipeline_version, blob_sha256=… | doc_id=…)`
- `land_item(session, graph, minio, location_id, content_http) -> Landed`; raises `DownloadMismatch`; the caller commits and decides dispatch
- host CLIs: `python -m backend.sync.downloader [--folder-id ID …] [--limit N]`, `python -m backend.sync.export_blobs --folder-id ID OUT_DIR`

Consumes:
- MinIO buckets (platform/compose-stack)

## Workspace (files to touch when modifying this feature)

Keep this list exact. A plan sheet copies it and adds only what the task truly needs.

- `backend/sync/downloader.py`
- `backend/postgres/models/registry.py`
- `backend/storage/minio.py`
- `backend/sync/export_blobs.py`
- `backend/tests/unit/storage/test_minio.py`
- `backend/tests/unit/sync/test_export_blobs.py`
- `backend/tests/unit/sync/test_downloader.py`
- `backend/tests/integration/registry/`

## Rubric (what "done" means for this feature)

- [ ] Same content in two folders yields one blob and one document
- [ ] Parallel downloads of new content cannot create two documents
- [ ] Downloads resume from the last committed range
- [ ] Job key never contains a location id
- [ ] Tests listed above pass; status entry written; this map updated; plan sheet deleted

## Change log

| Date | Session | Change |
|------|---------|--------|
| 2026-10-21 | Lead | Map created from the architecture manual |
| 2026-10-21 | S1 | MinIO store module (get/put/presign/buckets); 11 tests, green against S4's pinned MinIO image |
| 2026-10-21 | S1 | Downloader core and job keys; 6 tests, green against ParadeDB pg17 + pinned MinIO |
| 2026-10-22 | S1 | Host download CLI and read-only export; live: the 247 accepted files of the 11 allowlisted subtrees landed in the stack MinIO, all quickXorHash-verified |

## Related

- `.wiki/index.md`
