"""Files found inside other files become blobs of their own (file 05 ``blob_derivations``). Owner: S1.

One function for every producer: S2's A1.9 (Excel objects embedded in Word files), S6's Route G
(archive members), PDF attachments. Content-addressed and idempotent: the bytes go to
``dcl-raw/{sha256[:2]}/{sha256}`` once, the ``blobs`` row is insert-if-absent, the derivation row is keyed
by ``(parent, member_path)``. The next dispatch turns each child into a document
(``backend.dispatcher.routing.dispatch_derived``).
"""

import hashlib
from collections.abc import Iterable

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from backend.dispatcher.contract import DerivedBlob
from backend.postgres.models import Blob, BlobDerivation
from backend.storage.minio import RAW, BucketStore, raw_key, uri


def register_derived_blobs(
    session: Session, raw: BucketStore, parent_blob_sha256: str, blobs: Iterable[DerivedBlob]
) -> list[str]:
    """Store and link each derived blob; returns the child sha256s in order."""
    children = []
    for blob in blobs:
        if blob.data is not None:
            sha = hashlib.sha256(blob.data).hexdigest()
            if session.get(Blob, sha) is None:
                raw.put(raw_key(sha), blob.data)
            session.execute(
                insert(Blob)
                .values(sha256=sha, size_bytes=len(blob.data), minio_uri=uri(RAW, raw_key(sha)))
                .on_conflict_do_nothing(index_elements=["sha256"])
            )
        else:
            sha = blob.blob_sha256
            if session.scalar(select(Blob.sha256).where(Blob.sha256 == sha)) is None:
                raise LookupError(f"derived blob {blob.member_path}: blob {sha} is not stored")
        session.execute(
            insert(BlobDerivation)
            .values(
                parent_blob_sha256=parent_blob_sha256,
                member_path=blob.member_path,
                child_blob_sha256=sha,
                kind=str(blob.kind),
            )
            .on_conflict_do_update(
                index_elements=["parent_blob_sha256", "member_path"],
                set_={"child_blob_sha256": sha, "kind": str(blob.kind), "gate_reason": None},
            )
        )
        children.append(sha)
    session.flush()
    return children
