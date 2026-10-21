"""All SQLAlchemy models. Importing this package registers every table on ``Base.metadata``."""

from backend.postgres.models.documents import Document, DocumentRelation, DocumentSource
from backend.postgres.models.entities import Entity, EntityAlias, EntityMention, NumericFact
from backend.postgres.models.nodes import Asset, DocumentNode
from backend.postgres.models.ops import PipelineConfig
from backend.postgres.models.registry import Blob, BlobDerivation, DriveFolder, DriveItem, Job, SyncRoot
from backend.postgres.models.review import AuditEvent

__all__ = [
    "Asset",
    "AuditEvent",
    "Blob",
    "BlobDerivation",
    "Document",
    "DocumentNode",
    "DocumentRelation",
    "DocumentSource",
    "DriveFolder",
    "DriveItem",
    "Entity",
    "EntityAlias",
    "EntityMention",
    "Job",
    "NumericFact",
    "PipelineConfig",
    "SyncRoot",
]
