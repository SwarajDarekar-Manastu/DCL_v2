"""All SQLAlchemy models. Importing this package registers every table on ``Base.metadata``."""

from backend.postgres.models.benchmark import BenchmarkCase, BenchmarkResult, BenchmarkRun
from backend.postgres.models.documents import Document, DocumentRelation, DocumentSource
from backend.postgres.models.entities import Entity, EntityAlias, EntityMention, NumericFact
from backend.postgres.models.nodes import Asset, DocumentNode
from backend.postgres.models.ops import LlmCall, PipelineConfig
from backend.postgres.models.registry import Blob, BlobDerivation, DriveFolder, DriveItem, Job, SyncRoot
from backend.postgres.models.review import AuditEvent, ReviewFlag, Rule
from backend.postgres.models.telemetry import TelemetryChannel, TelemetryRun
from backend.postgres.models.traces import AnswerTrace
from backend.postgres.models.users import User

__all__ = [
    "AnswerTrace",
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
    "LlmCall",
    "NumericFact",
    "PipelineConfig",
    "ReviewFlag",
    "Rule",
    "SyncRoot",
    "TelemetryChannel",
    "TelemetryRun",
    "User",
]
