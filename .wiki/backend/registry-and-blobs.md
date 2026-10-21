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
- `backend/sync/downloader.py` (planned)
- `backend/postgres/models/registry.py` (M1 tables, done with backend/schema-and-migrations)
- `backend/storage/minio.py` (client from `Group.MINIO`, `BucketStore.get/put`, `presign_get` 15 min, `ensure_buckets`, `raw_key`, `uri`/`parse_uri`)

Tests and fixtures:
- `backend/tests/unit/storage/test_minio.py` (server tests need `DCL_TEST_MINIO_ENDPOINT` on a disposable MinIO)
- `backend/tests/unit/sync/test_downloader.py` (planned)
- `backend/tests/integration/registry/`

## Interfaces

Provides:
- `BucketStore(client, "dcl-cir").get(key) -> bytes | None` / `.put(key, data, content_type, metadata) -> s3 URI` (S2 vision cache, staged payloads)
- `presign_get(client, minio_uri)` (S3 viewer and assets; the caller checks the session)
- blobs rows
- location→blob links
- jobs idempotency keys

Consumes:
- MinIO buckets (platform/compose-stack)

## Workspace (files to touch when modifying this feature)

Keep this list exact. A plan sheet copies it and adds only what the task truly needs.

- `backend/sync/downloader.py`
- `backend/postgres/models/registry.py`
- `backend/storage/minio.py`
- `backend/tests/unit/storage/test_minio.py`
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

## Related

- `.wiki/index.md`
