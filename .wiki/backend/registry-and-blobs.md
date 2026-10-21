# Registry, content-addressed blobs, downloader

| Field | Value |
|-------|-------|
| Feature id | `backend/registry-and-blobs` |
| Status | planned |
| Owner session | S1 |
| Spec | docs/architecture/02_phase1_ingestion_sync.md §5–§7; 05_storage_schema.md §4.1 |
| Last updated | 2026-10-21 |

## Purpose

Download accepted items into MinIO keyed by SHA-256, verify quickXorHash, deduplicate by (quick_xor_hash,size), and maintain drive_items/drive_folders/blobs/blob_derivations.

## Location

Code:
- `services/sync/downloader.py`
- `services/common/db/models/registry.py`
- `services/common/minio_client.py`

Tests and fixtures:
- `tests/unit/sync/test_downloader.py`
- `tests/integration/registry/`

## Interfaces

Provides:
- blobs rows
- location→blob links
- jobs idempotency keys

Consumes:
- MinIO buckets (platform/compose-stack)

## Workspace (files to touch when modifying this feature)

Keep this list exact. A plan sheet copies it and adds only what the task truly needs.

- `services/sync/downloader.py`
- `services/common/db/models/registry.py`
- `services/common/minio_client.py`
- `tests/unit/sync/test_downloader.py`
- `tests/integration/registry/`

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

## Related

- `.wiki/index.md`
