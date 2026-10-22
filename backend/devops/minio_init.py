"""First-start MinIO setup for the dcl-v2 stack (docs/architecture/05 §1, §6; 10 §3). Idempotent.

Creates the five buckets, enables versioning on dcl-raw and dcl-cir, and sets the lifecycle rules:
download temp objects under dcl-raw/_incoming/ lose noncurrent versions after 1 day and their delete markers;
the vision cache expires 180 days after last write; chat uploads under dcl-exports/uploads/ expire after
1 day; other exports after 180 days. Creates the application user with a policy limited to the five buckets.
Works against the pinned MinIO build and RustFS 1.0.3 (the M6 object store).
Runs in the one-shot `minio-init` compose service with the root pair; the application itself only ever
holds DCL_MINIO_ACCESS_KEY / DCL_MINIO_SECRET_KEY. Prints names, never credentials.
"""

import json
import os
import sys
from urllib.parse import urlparse

from minio import Minio
from minio.commonconfig import ENABLED, Filter
from minio.credentials import StaticProvider
from minio.lifecycleconfig import Expiration, LifecycleConfig, NoncurrentVersionExpiration, Rule
from minio.minioadmin import MinioAdmin
from minio.versioningconfig import VersioningConfig

from backend.storage.minio import BUCKETS, CIR, EXPORTS, RAW

VERSIONED = (RAW, CIR)
APP_POLICY = "dcl-app"
LIFECYCLE = {
    RAW: [
        Rule(
            ENABLED,
            rule_filter=Filter(prefix="_incoming/"),
            rule_id="incoming-temp-cleanup",
            noncurrent_version_expiration=NoncurrentVersionExpiration(noncurrent_days=1),
            expiration=Expiration(expired_object_delete_marker=True),
        )
    ],
    CIR: [
        Rule(
            ENABLED,
            rule_filter=Filter(prefix="_vision_cache/"),
            rule_id="vision-cache-180d",
            expiration=Expiration(days=180),
        )
    ],
    EXPORTS: [
        Rule(
            ENABLED,
            rule_filter=Filter(prefix="uploads/"),
            rule_id="chat-uploads-24h",
            expiration=Expiration(days=1),
        ),
        Rule(ENABLED, rule_filter=Filter(prefix=""), rule_id="exports-180d", expiration=Expiration(days=180)),
    ],
}


def env(name: str) -> str:
    value = os.environ.get(name, "")
    if not value:
        sys.exit(f"minio-init: {name} is required")
    return value


def app_policy() -> dict:
    resources = [f"arn:aws:s3:::{b}" for b in BUCKETS] + [f"arn:aws:s3:::{b}/*" for b in BUCKETS]
    return {
        "Version": "2012-10-17",
        "Statement": [{"Effect": "Allow", "Action": ["s3:*"], "Resource": resources}],
    }


def main() -> None:
    endpoint = urlparse(env("DCL_MINIO_ENDPOINT"))
    secure = endpoint.scheme == "https"
    root = StaticProvider(env("MINIO_ROOT_USER"), env("MINIO_ROOT_PASSWORD"))
    client = Minio(endpoint.netloc, credentials=root, secure=secure)
    for bucket in BUCKETS:
        if not client.bucket_exists(bucket):
            client.make_bucket(bucket)
            print(f"minio-init: created bucket {bucket}")
    for bucket in VERSIONED:
        client.set_bucket_versioning(bucket, VersioningConfig(ENABLED))
    for bucket, rules in LIFECYCLE.items():
        client.set_bucket_lifecycle(bucket, LifecycleConfig(rules))
    access_key, secret_key = env("DCL_MINIO_ACCESS_KEY"), env("DCL_MINIO_SECRET_KEY")
    if access_key != os.environ["MINIO_ROOT_USER"]:
        admin = MinioAdmin(endpoint=endpoint.netloc, credentials=root, secure=secure)
        admin.policy_add(APP_POLICY, policy=app_policy())
        admin.user_add(access_key, secret_key)
        # set-user-or-group-policy, not attach_policy: RustFS answers attach with a payload minio-py cannot
        # decrypt (AEAD id 2), and set is idempotent on both stores.
        admin.policy_set(APP_POLICY, user=access_key)
        if APP_POLICY not in json.loads(admin.user_info(access_key)).get("policyName", "").split(","):
            sys.exit(f"minio-init: policy {APP_POLICY} is not attached to the application user")
        print(f"minio-init: application user has policy {APP_POLICY}")
    print(f"minio-init: ok ({len(BUCKETS)} buckets, versioning on {', '.join(VERSIONED)})")


if __name__ == "__main__":
    main()
