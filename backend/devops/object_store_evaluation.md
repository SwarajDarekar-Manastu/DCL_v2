# Object store evaluation: replacing archived MinIO

Date: 2026-10-22. Author: S4. Decision owner: DCL Lead, before M6 (docs/architecture/09 §H.1).

**Recommendation: RustFS 1.0.3**, the only candidate that met every data-plane requirement and enforced lifecycle expiry. Before adopting it, one gap must be closed: creating the application user and its bucket-scoped policy through RustFS's own admin path, because the MinIO admin client could not do it.

## Method

Each store ran single-node in a throwaway container on this host. `backend/devops/ci/s3_compat_check.py` then ran the operations DCL relies on, with the same `minio` Python client that S1's storage code uses. A second script tested lifecycle enforcement and the admin API. MinIO, the archived build we run today, was the baseline.

| Check | What it proves |
|-------|----------------|
| bucket_create, put_get_metadata | bucket listing, bytes and user metadata round-trip, prefix listing |
| multipart_upload | a 20 MiB object in 5 MiB parts |
| versioning, version_exact_delete | two versions, old version readable, delete leaves a marker, version-exact delete (S1's temp cleanup) |
| lifecycle_prefix_expiration, lifecycle_noncurrent_expiration | the rules `minio-init` sets (vision cache, `_incoming/`) are accepted and read back |
| lifecycle enforcement | an object under an already-expired prefix rule disappears; others stay |
| presigned_get | the 15-minute links the Console and viewer use |
| duckdb_httpfs_parquet | Route C's DuckDB `read_parquet('s3://…')` |
| admin API | `minio-init` creates the app user and a bucket-scoped policy (`MinioAdmin`) |

## Results

| Check | MinIO (archived, baseline) | RustFS 1.0.3 | SeaweedFS 4.48 | Garage v2.4.1 |
|-------|----------------------------|--------------|----------------|---------------|
| Basic object operations, multipart | pass | pass | pass | pass |
| Versioning, delete markers, version-exact delete | pass | pass | pass | **fail**: `PutBucketVersioning` not implemented |
| Lifecycle rules accepted and read back | pass | pass | pass | **fail** on noncurrent-version rules |
| Lifecycle enforced | pass | pass | **fail**: expired object still served after 10 min | not tested |
| Presigned GET | pass | pass | pass | pass |
| DuckDB httpfs Parquet | pass | pass | pass | pass |
| Admin API for user + policy | pass; policy limits the user to its buckets | **fail** with the MinIO client (`Unknown AEAD ID 2`); RustFS has its own admin path, not yet tested | **fail**: no admin API (405); users come from a config file or `weed shell` | own CLI (`garage key`) |
| License, maintenance | AGPL-3.0, archived | Apache-2.0, active (pushed 2026-10-21) | Apache-2.0, active | AGPL-3.0, active |
| Image size | 285 MB (our build) | 417 MB | 724 MB | 99 MB |

## Assessment

- **Garage** is out: no bucket versioning, which file 10 §3 requires for `dcl-raw` and `dcl-cir`.
- **SeaweedFS** accepts lifecycle rules but did not enforce a past-dated expiry within 10 minutes. It has no admin API for users either. The vision-cache expiry and S1's temp cleanup would become manual jobs.
- **RustFS** behaved like MinIO on every data-plane check, including enforcement. Its admin protocol differs from MinIO's, so `minio-init` needs a RustFS-specific way to create the user and policy.

## Before adopting RustFS

1. ~~Make `minio-init` create the app user and its policy on RustFS, then re-run the policy-scope test.~~ Done 2026-10-22. The failure was only in the reply: RustFS applies `attach_policy` but answers with a payload minio-py cannot decrypt (AEAD id 2). `minio-init` now uses `policy_set` (set-user-or-group-policy) and reads the mapping back with `user_info`. Two consecutive full runs exit 0 on RustFS 1.0.3 and on the pinned MinIO build, and on both the app user writes `dcl-raw` and gets AccessDenied on a bucket outside its policy.
2. Watch lifecycle enforcement with the real rules for a day: noncurrent versions under `_incoming/` and vision-cache expiry.
3. Load-test it with the M6-scale object count (about 5,200 blobs plus CIR and assets) and compare latency with MinIO.
4. Migration (before M6): stop writers, copy every bucket with `rclone sync` or `mc mirror`. Only current versions carry over, which is acceptable because no history is needed yet. Then switch `DCL_MINIO_ENDPOINT` and re-run `s3_compat_check.py` against the new store.

## Reproduce

```bash
uv run python backend/devops/ci/s3_compat_check.py --endpoint http://127.0.0.1:<port> --access-key <key> --secret-key <secret> --name <store>
```
