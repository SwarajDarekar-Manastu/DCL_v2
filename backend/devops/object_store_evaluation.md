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
2. Watch lifecycle enforcement with the real rules for a day. **Running.** On 2026-10-22 at 07:53Z, `lifecycle_watch.py seed` applied `minio-init`'s rules to a dedicated RustFS 1.0.3 (`dcl-s4-rustfs-watch`, 127.0.0.1:9293, volume `dcl-s4-rustfs-watch-data`). It then wrote three cases the 1-day rules must clear: a noncurrent version under `dcl-raw/_incoming/`, a deleted object and its marker under `_incoming/`, and a chat upload. It also wrote three controls that must stay: versions outside `_incoming/`, an export, and a vision-cache entry. S3 rounds lifecycle days up to the next midnight UTC, so the cases are due by 2026-10-24 00:00Z. `check` exits 2 while the cases are pending, 0 when every case is as expected, and 1 when a control lost data or a case is more than 2 h overdue.
3. ~~Load-test it with the M6-scale object count and compare latency with MinIO.~~ Done 2026-10-22, see "M6-scale load test" below. Verdict: RustFS takes the M6 object set with no errors; writes are about twice as slow as MinIO at the median and full listings are 3–7× slower, which is acceptable for DCL's write-once, read-by-key pattern.
4. Migration (before M6): stop writers, copy every bucket with `rclone sync` or `mc mirror`. Only current versions carry over, which is acceptable because no history is needed yet. Then switch `DCL_MINIO_ENDPOINT` and re-run `s3_compat_check.py` against the new store.

## M6-scale load test (step 3)

`backend/devops/ci/object_store_load.py` wrote 20,800 objects (3.95 GB) with S1's key layout and the minio-py client: 5,200 raw blobs in versioned `dcl-raw` (lognormal sizes, median 203 KB, capped at 4 MB), 5,200 CIR JSONs in versioned `dcl-cir` and 10,400 page assets in `dcl-assets`. It used 16 client threads. Afterwards it listed every bucket in full and stat-read and fully read 2,000 sampled objects, checking each against its sha256. Each store ran in a fresh container on a fresh volume on the dev host (i5-14600K, 15 GiB RAM, NVMe at 94 % full). I ran the pair twice in opposite orders (RustFS then MinIO, then MinIO then RustFS); values are run 1 / run 2.

| Measure | RustFS 1.0.3 | MinIO (pinned build) |
|---------|--------------|----------------------|
| Errors, count and content mismatches | 0 / 0 | 0 / 0 |
| Write all 20,800 objects | 53.8 s / 52.5 s (70 / 72 MiB/s) | 34.7 s / 27.3 s (109 / 138 MiB/s) |
| put raw p50 / p99 (ms) | 43.9 / 103.6, 43.9 / 85.9 | 22.6 / 100.5, 20.5 / 99.7 |
| put CIR p50 (ms) | 35.1, 35.1 | 20.7, 18.6 |
| put asset p50 (ms) | 36.1, 36.0 | 20.9, 18.8 |
| stat p50 / p99 (ms) | 3.2 / 16.1, 3.6 / 26.9 | 3.3 / 22.2, 3.2 / 15.8 |
| get p50 / p99 (ms) | 7.9 / 26.3, 8.7 / 41.8 | 8.0 / 34.8, 8.3 / 26.9 |
| Full listing raw / CIR / assets (s) | 2.8 / 1.9 / 4.1, 6.5 / 4.0 / 4.4 | 0.65 / 0.59 / 0.98, 0.61 / 0.60 / 1.0 |

What it means for M6:
- **Writes** are about 2× slower at the median, while p99 is similar. Even so, RustFS sustains about 390 objects/s. That is far above what the pipeline writes, since every DCL write follows a download or a parse step that takes seconds.
- **Reads by key** (stat and get), which is how the pipeline and the viewer use the store, match MinIO at the median. Their p99 varies between runs on both stores.
- **Full listings** take seconds instead of under one second. Only sweeps and retention jobs list, and seconds per 10,000 objects is acceptable for them.
- **Not measured:** what limits RustFS's write rate (CPU, fsync or client concurrency). Its container was not sampled during the run. I did not tune that, because the rate is not a constraint for DCL.

## Reproduce

```bash
uv run python backend/devops/ci/object_store_load.py --endpoint http://127.0.0.1:<port> --access-key <key> --secret-key <secret> --name <store>
uv run python backend/devops/ci/lifecycle_watch.py seed|check --endpoint http://127.0.0.1:<port> --access-key <root> --secret-key <secret>
uv run python backend/devops/ci/s3_compat_check.py --endpoint http://127.0.0.1:<port> --access-key <key> --secret-key <secret> --name <store>
```
