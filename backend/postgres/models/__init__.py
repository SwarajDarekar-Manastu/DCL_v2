"""All SQLAlchemy models. Importing this package registers every table on ``Base.metadata``."""

from backend.postgres.models.benchmark import BenchmarkCase, BenchmarkResult, BenchmarkRun
from backend.postgres.models.documents import Document, DocumentRelation, DocumentSource
from backend.postgres.models.entities import Entity, EntityAlias, EntityMention, NumericFact
from backend.postgres.models.nodes import Asset, DocumentNode
from backend.postgres.models.ops import PipelineConfig
from backend.postgres.models.registry import Blob, BlobDerivation, DriveFolder, DriveItem, Job, SyncRoot
from backend.postgres.models.review import AuditEvent, ReviewFlag, Rule

__all__ = [
    "Asset",
    "AuditEvent",
    "BenchmarkCase",
    "BenchmarkResult",
    "BenchmarkRun",
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
    "ReviewFlag",
    "Rule",
    "SyncRoot",
]
