# ruff: noqa: E501  (literal CHECK value lists stay on one line each)
"""Document, node and asset tables (M2), entity and fact tables (M4), audit_events.

Created now because the code that writes them is being built (Lead decision 2026-10-21).
CHECK value lists are literal (compared with backend/postgres/enums.py by the schema tests).
The HNSW indexes are hand-written (autogenerate skips the hnsw_ prefix). The BM25 index comes
in its own migration with the retrieval work (file 01 §5.5: pin the DDL in one file).

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-22
"""

from collections.abc import Sequence

import pgvector.sqlalchemy
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


HNSW_INDEXES = (
    ("hnsw_document_nodes_embedding", "embedding"),
    ("hnsw_document_nodes_image_embedding", "image_embedding"),
)


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.create_table(
        "audit_events",
        sa.Column("event_id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("actor", sa.Text(), nullable=False),
        sa.Column("entity_type", sa.Text(), nullable=False),
        sa.Column("entity_id", sa.Text(), nullable=False),
        sa.Column("action", sa.Text(), nullable=False),
        sa.Column("before", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("after", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.CheckConstraint(
            "entity_type IN ('flag', 'case', 'rule', 'entity', 'config', 'benchmark_case', 'document')",
            name=op.f("ck_audit_events_entity_type"),
        ),
        sa.PrimaryKeyConstraint("event_id", name=op.f("pk_audit_events")),
    )
    op.create_index(
        op.f("ix_audit_events_entity_type_entity_id_at"),
        "audit_events",
        ["entity_type", "entity_id", "at"],
        unique=False,
    )
    op.create_table(
        "documents",
        sa.Column("doc_id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("route", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=True),
        sa.Column("doc_kind", sa.Text(), server_default="unknown", nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("source_origin", sa.Text(), server_default="internal", nullable=False),
        sa.Column("trust_tier", sa.SmallInteger(), nullable=True),
        sa.Column("publisher", sa.Text(), nullable=True),
        sa.Column(
            "external_ids",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("test_plan_id", sa.Text(), nullable=True),
        sa.Column("test_run_id", sa.Text(), nullable=True),
        sa.Column("hardware_item", sa.Text(), nullable=True),
        sa.Column("doc_date", sa.Date(), nullable=True),
        sa.Column("date_source", sa.Text(), nullable=True),
        sa.Column("standard_id", sa.Text(), nullable=True),
        sa.Column("standard_revision", sa.Text(), nullable=True),
        sa.Column("revision_marker", sa.Text(), nullable=True),
        sa.Column("classification_marking", sa.Text(), nullable=True),
        sa.Column("language", sa.Text(), nullable=True),
        sa.Column(
            "languages_detected", sa.ARRAY(sa.Text()), server_default=sa.text("'{}'::text[]"), nullable=False
        ),
        sa.Column("number_locale", sa.Text(), nullable=True),
        sa.Column("page_count", sa.Integer(), nullable=True),
        sa.Column("unit_count", sa.Integer(), nullable=True),
        sa.Column(
            "folder_context",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "metadata_sources",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "enrichment",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("catalog", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("entity_ids", sa.ARRAY(sa.UUID()), server_default=sa.text("'{}'::uuid[]"), nullable=False),
        sa.Column("search_text", sa.Text(), nullable=True),
        sa.Column("cir_uri", sa.Text(), nullable=True),
        sa.Column("staged_payload_uri", sa.Text(), nullable=True),
        sa.Column("parser_version", sa.Integer(), nullable=True),
        sa.Column("pipeline_version", sa.Integer(), nullable=True),
        sa.Column("cloud_processed", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("indexed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "(status = 'HALTED') = (staged_payload_uri IS NOT NULL)",
            name=op.f("ck_documents_staged_when_halted"),
        ),
        sa.CheckConstraint(
            "doc_kind IN ('standard', 'test_plan', 'test_report', 'failure_report', 'calibration', 'risk_assessment', 'material_spec', 'procedure', 'workshop_slides', 'code', 'tooling_doc', 'telemetry_run', 'engineering_table', 'hardware_photo', 'plot_figure', 'diagram', 'schema', 'video_transcript', 'video_timeline', 'cae_package', 'cad_reference', 'config', 'vendor_brochure', 'datasheet', 'academic_paper', 'article', 'book_excerpt', 'conference_paper', 'unknown')",
            name=op.f("ck_documents_doc_kind"),
        ),
        sa.CheckConstraint(
            "route IN ('A1', 'A2', 'B', 'C', 'D', 'E', 'F', 'G')", name=op.f("ck_documents_route")
        ),
        sa.CheckConstraint(
            "source_origin IN ('internal', 'external_kept')", name=op.f("ck_documents_source_origin")
        ),
        sa.CheckConstraint(
            "status IN ('WAITING_FOR_ROUTE', 'PROCESSING', 'HALTED', 'ACTIVE', 'ACTIVE_WITH_SOFT_FLAGS', 'SUPERSEDED', 'QUARANTINED', 'DELETED', 'FAILED')",
            name=op.f("ck_documents_status"),
        ),
        sa.CheckConstraint("trust_tier BETWEEN 1 AND 6", name=op.f("ck_documents_trust_tier")),
        sa.PrimaryKeyConstraint("doc_id", name=op.f("pk_documents")),
    )
    op.create_index(op.f("ix_documents_doc_kind_status"), "documents", ["doc_kind", "status"], unique=False)
    op.create_index(
        op.f("ix_documents_enrichment"),
        "documents",
        ["enrichment"],
        unique=False,
        postgresql_using="gin",
        postgresql_ops={"enrichment": "jsonb_path_ops"},
    )
    op.create_index(
        op.f("ix_documents_entity_ids"), "documents", ["entity_ids"], unique=False, postgresql_using="gin"
    )
    op.create_index(
        op.f("ix_documents_source_origin_trust_tier"),
        "documents",
        ["source_origin", "trust_tier"],
        unique=False,
    )
    op.create_index(op.f("ix_documents_standard_id"), "documents", ["standard_id"], unique=False)
    op.create_index(op.f("ix_documents_status"), "documents", ["status"], unique=False)
    op.create_index(op.f("ix_documents_test_plan_id"), "documents", ["test_plan_id"], unique=False)
    op.create_index(op.f("ix_documents_test_run_id"), "documents", ["test_run_id"], unique=False)
    op.create_table(
        "assets",
        sa.Column("asset_id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("minio_uri", sa.Text(), nullable=False),
        sa.Column("blob_sha256", sa.CHAR(length=64), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("page_no", sa.Integer(), nullable=True),
        sa.Column("bbox", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("t_ms", sa.BigInteger(), nullable=True),
        sa.Column("width", sa.Integer(), nullable=True),
        sa.Column("height", sa.Integer(), nullable=True),
        sa.Column("bytes", sa.BigInteger(), nullable=True),
        sa.Column("phash", sa.Text(), nullable=True),
        sa.Column("photo_cluster_id", sa.UUID(), nullable=True),
        sa.Column("is_cluster_representative", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column(
            "exif",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "kind IN ('page_render', 'figure_crop', 'handwriting_crop', 'table_crop', 'photo_web', 'photo_thumb', 'photo_in_doc', 'video_frame', 'diagram_render', 'sparkline')",
            name=op.f("ck_assets_kind"),
        ),
        sa.ForeignKeyConstraint(["blob_sha256"], ["blobs.sha256"], name=op.f("fk_assets_blob_sha256_blobs")),
        sa.PrimaryKeyConstraint("asset_id", name=op.f("pk_assets")),
        sa.UniqueConstraint("minio_uri", name=op.f("uq_assets_minio_uri")),
    )
    op.create_index(op.f("ix_assets_blob_sha256"), "assets", ["blob_sha256"], unique=False)
    op.create_table(
        "document_relations",
        sa.Column("doc_id_a", sa.UUID(), nullable=False),
        sa.Column("doc_id_b", sa.UUID(), nullable=False),
        sa.Column("relation", sa.Text(), nullable=False),
        sa.Column("score", sa.Float(), nullable=True),
        sa.Column("created_by", sa.Text(), server_default="system", nullable=False),
        sa.CheckConstraint(
            "relation = 'SUPERSEDES' OR doc_id_a < doc_id_b",
            name=op.f("ck_document_relations_symmetric_order"),
        ),
        sa.CheckConstraint(
            "relation IN ('SUPERSEDES', 'NEAR_DUPLICATE', 'REFERENCES')",
            name=op.f("ck_document_relations_relation"),
        ),
        sa.ForeignKeyConstraint(
            ["doc_id_a"],
            ["documents.doc_id"],
            name=op.f("fk_document_relations_doc_id_a_documents"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["doc_id_b"],
            ["documents.doc_id"],
            name=op.f("fk_document_relations_doc_id_b_documents"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("doc_id_a", "doc_id_b", "relation", name=op.f("pk_document_relations")),
    )
    op.create_index(op.f("ix_document_relations_doc_id_b"), "document_relations", ["doc_id_b"], unique=False)
    op.create_table(
        "document_sources",
        sa.Column("doc_id", sa.UUID(), nullable=False),
        sa.Column("blob_sha256", sa.CHAR(length=64), nullable=False),
        sa.Column("role", sa.Text(), nullable=False),
        sa.CheckConstraint(
            "role IN ('primary', 'part', 'visual_twin', 'channel_map', 'calibration', 'bibliography', 'attachment', 'replacement')",
            name=op.f("ck_document_sources_role"),
        ),
        sa.ForeignKeyConstraint(
            ["blob_sha256"], ["blobs.sha256"], name=op.f("fk_document_sources_blob_sha256_blobs")
        ),
        sa.ForeignKeyConstraint(
            ["doc_id"],
            ["documents.doc_id"],
            name=op.f("fk_document_sources_doc_id_documents"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("doc_id", "blob_sha256", "role", name=op.f("pk_document_sources")),
    )
    op.create_index(
        op.f("ix_document_sources_blob_sha256"), "document_sources", ["blob_sha256"], unique=False
    )
    op.create_index(
        "uq_document_sources_primary_blob",
        "document_sources",
        ["blob_sha256"],
        unique=True,
        postgresql_where=sa.text("role = 'primary'"),
    )
    op.create_index(
        "uq_document_sources_primary_per_doc",
        "document_sources",
        ["doc_id"],
        unique=True,
        postgresql_where=sa.text("role = 'primary'"),
    )
    op.create_table(
        "entities",
        sa.Column("entity_id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("type", sa.Text(), nullable=False),
        sa.Column("canonical_name", sa.Text(), nullable=False),
        sa.Column("canonical_key", sa.Text(), nullable=False),
        sa.Column("created_by", sa.Text(), nullable=False),
        sa.Column("first_seen_doc_id", sa.UUID(), nullable=True),
        sa.CheckConstraint(
            "created_by IN ('seed', 'system', 'operator')", name=op.f("ck_entities_created_by")
        ),
        sa.CheckConstraint(
            "type IN ('subsystem', 'component', 'material', 'propellant', 'catalyst', 'sensor_tag', 'part_number', 'test_id', 'standard_clause', 'person_role', 'organization', 'vendor', 'product', 'tool_software', 'equation', 'failure_mode')",
            name=op.f("ck_entities_type"),
        ),
        sa.ForeignKeyConstraint(
            ["first_seen_doc_id"],
            ["documents.doc_id"],
            name=op.f("fk_entities_first_seen_doc_id_documents"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("entity_id", name=op.f("pk_entities")),
        sa.UniqueConstraint("type", "canonical_key", name=op.f("uq_entities_type_canonical_key")),
    )
    op.create_index(op.f("ix_entities_first_seen_doc_id"), "entities", ["first_seen_doc_id"], unique=False)
    op.create_table(
        "document_nodes",
        sa.Column("node_id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("doc_id", sa.UUID(), nullable=False),
        sa.Column("parent_node_id", sa.UUID(), nullable=True),
        sa.Column("node_type", sa.Text(), nullable=False),
        sa.Column("level", sa.SmallInteger(), server_default=sa.text("0"), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("breadcrumb", sa.Text(), nullable=True),
        sa.Column("language", sa.Text(), nullable=True),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("content_en", sa.Text(), nullable=True),
        sa.Column("content_codes", sa.Text(), nullable=True),
        sa.Column("content_sha256", sa.CHAR(length=64), nullable=True),
        sa.Column("embed_text", sa.Text(), nullable=True),
        sa.Column("embed_text_hash", sa.CHAR(length=64), nullable=True),
        sa.Column("embedding", pgvector.sqlalchemy.halfvec.HALFVEC(dim=768), nullable=True),
        sa.Column("image_embedding", pgvector.sqlalchemy.halfvec.HALFVEC(dim=768), nullable=True),
        sa.Column("embedding_model", sa.Text(), nullable=True),
        sa.Column("token_count", sa.Integer(), nullable=True),
        sa.Column("page_no", sa.Integer(), nullable=True),
        sa.Column("page_end", sa.Integer(), nullable=True),
        sa.Column("bbox", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("line_start", sa.Integer(), nullable=True),
        sa.Column("line_end", sa.Integer(), nullable=True),
        sa.Column("t_start_ms", sa.BigInteger(), nullable=True),
        sa.Column("t_end_ms", sa.BigInteger(), nullable=True),
        sa.Column("sheet_name", sa.Text(), nullable=True),
        sa.Column("cell_range", sa.Text(), nullable=True),
        sa.Column("asset_id", sa.UUID(), nullable=True),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("needs_review", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("doc_kind", sa.Text(), nullable=True),
        sa.Column("test_plan_id", sa.Text(), nullable=True),
        sa.Column("source_origin", sa.Text(), nullable=True),
        sa.Column("trust_tier", sa.SmallInteger(), nullable=True),
        sa.Column("doc_status", sa.Text(), nullable=True),
        sa.Column(
            "metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("pipeline_version", sa.Integer(), nullable=True),
        sa.CheckConstraint(
            "doc_kind IN ('standard', 'test_plan', 'test_report', 'failure_report', 'calibration', 'risk_assessment', 'material_spec', 'procedure', 'workshop_slides', 'code', 'tooling_doc', 'telemetry_run', 'engineering_table', 'hardware_photo', 'plot_figure', 'diagram', 'schema', 'video_transcript', 'video_timeline', 'cae_package', 'cad_reference', 'config', 'vendor_brochure', 'datasheet', 'academic_paper', 'article', 'book_excerpt', 'conference_paper', 'unknown')",
            name=op.f("ck_document_nodes_doc_kind"),
        ),
        sa.CheckConstraint(
            "doc_status IN ('WAITING_FOR_ROUTE', 'PROCESSING', 'HALTED', 'ACTIVE', 'ACTIVE_WITH_SOFT_FLAGS', 'SUPERSEDED', 'QUARANTINED', 'DELETED', 'FAILED')",
            name=op.f("ck_document_nodes_doc_status"),
        ),
        sa.CheckConstraint(
            "node_type IN ('parent', 'child', 'table', 'table_row', 'figure', 'code_symbol', 'module_header', 'slide', 'transcript_window', 'video_event', 'run_summary', 'photo', 'diagram_summary', 'diagram_component', 'question_proxy', 'config')",
            name=op.f("ck_document_nodes_node_type"),
        ),
        sa.CheckConstraint(
            "source IN ('printed', 'ocr', 'vlm', 'source_code', 'structured', 'human')",
            name=op.f("ck_document_nodes_source"),
        ),
        sa.CheckConstraint(
            "source_origin IN ('internal', 'external_kept')", name=op.f("ck_document_nodes_source_origin")
        ),
        sa.ForeignKeyConstraint(
            ["asset_id"], ["assets.asset_id"], name=op.f("fk_document_nodes_asset_id_assets")
        ),
        sa.ForeignKeyConstraint(
            ["doc_id"],
            ["documents.doc_id"],
            name=op.f("fk_document_nodes_doc_id_documents"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("node_id", name=op.f("pk_document_nodes")),
    )
    op.create_index(op.f("ix_document_nodes_asset_id"), "document_nodes", ["asset_id"], unique=False)
    op.create_index(
        op.f("ix_document_nodes_doc_id_ordinal"), "document_nodes", ["doc_id", "ordinal"], unique=False
    )
    op.create_index(op.f("ix_document_nodes_doc_kind"), "document_nodes", ["doc_kind"], unique=False)
    op.create_index(
        "ix_document_nodes_needs_review_doc_id",
        "document_nodes",
        ["doc_id"],
        unique=False,
        postgresql_where=sa.text("needs_review"),
    )
    op.create_index(op.f("ix_document_nodes_node_type"), "document_nodes", ["node_type"], unique=False)
    op.create_index(
        op.f("ix_document_nodes_parent_node_id"), "document_nodes", ["parent_node_id"], unique=False
    )
    op.create_index(
        op.f("ix_document_nodes_source_origin_trust_tier"),
        "document_nodes",
        ["source_origin", "trust_tier"],
        unique=False,
    )
    op.create_index(op.f("ix_document_nodes_test_plan_id"), "document_nodes", ["test_plan_id"], unique=False)
    op.create_table(
        "entity_aliases",
        sa.Column("type", sa.Text(), nullable=False),
        sa.Column("alias_key", sa.Text(), nullable=False),
        sa.Column("entity_id", sa.UUID(), nullable=False),
        sa.Column("alias", sa.Text(), nullable=False),
        sa.Column("created_by", sa.Text(), nullable=False),
        sa.Column("fuzzy_score", sa.Float(), nullable=True),
        sa.CheckConstraint(
            "created_by IN ('seed', 'system_exact', 'system_fuzzy', 'operator')",
            name=op.f("ck_entity_aliases_created_by"),
        ),
        sa.CheckConstraint(
            "type IN ('subsystem', 'component', 'material', 'propellant', 'catalyst', 'sensor_tag', 'part_number', 'test_id', 'standard_clause', 'person_role', 'organization', 'vendor', 'product', 'tool_software', 'equation', 'failure_mode')",
            name=op.f("ck_entity_aliases_type"),
        ),
        sa.ForeignKeyConstraint(
            ["entity_id"], ["entities.entity_id"], name=op.f("fk_entity_aliases_entity_id_entities")
        ),
        sa.PrimaryKeyConstraint("type", "alias_key", name=op.f("pk_entity_aliases")),
    )
    op.create_index(op.f("ix_entity_aliases_entity_id"), "entity_aliases", ["entity_id"], unique=False)
    op.create_table(
        "entity_mentions",
        sa.Column("mention_id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("node_id", sa.UUID(), nullable=False),
        sa.Column("doc_id", sa.UUID(), nullable=False),
        sa.Column("entity_id", sa.UUID(), nullable=False),
        sa.Column("surface", sa.Text(), nullable=False),
        sa.Column("span_start", sa.Integer(), nullable=True),
        sa.Column("span_end", sa.Integer(), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("source", sa.Text(), nullable=False),
        sa.CheckConstraint("source IN ('regex', 'llm', 'human')", name=op.f("ck_entity_mentions_source")),
        sa.ForeignKeyConstraint(
            ["doc_id"],
            ["documents.doc_id"],
            name=op.f("fk_entity_mentions_doc_id_documents"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["entity_id"], ["entities.entity_id"], name=op.f("fk_entity_mentions_entity_id_entities")
        ),
        sa.ForeignKeyConstraint(
            ["node_id"],
            ["document_nodes.node_id"],
            name=op.f("fk_entity_mentions_node_id_document_nodes"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("mention_id", name=op.f("pk_entity_mentions")),
    )
    op.create_index(op.f("ix_entity_mentions_doc_id"), "entity_mentions", ["doc_id"], unique=False)
    op.create_index(op.f("ix_entity_mentions_entity_id"), "entity_mentions", ["entity_id"], unique=False)
    op.create_index(op.f("ix_entity_mentions_node_id"), "entity_mentions", ["node_id"], unique=False)
    op.create_table(
        "numeric_facts",
        sa.Column("fact_id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("node_id", sa.UUID(), nullable=False),
        sa.Column("doc_id", sa.UUID(), nullable=False),
        sa.Column("quantity", sa.Text(), nullable=False),
        sa.Column("value_raw", sa.Text(), nullable=True),
        sa.Column("unit_raw", sa.Text(), nullable=True),
        sa.Column("value_si", sa.Float(), nullable=True),
        sa.Column("unit_si", sa.Text(), nullable=True),
        sa.Column("gauge_or_abs", sa.Text(), server_default="n/a", nullable=False),
        sa.Column("context", sa.Text(), nullable=True),
        sa.Column("span_start", sa.Integer(), nullable=True),
        sa.Column("span_end", sa.Integer(), nullable=True),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("suspect", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("needs_unit", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.CheckConstraint(
            "gauge_or_abs IN ('gauge', 'absolute', 'unknown', 'n/a')",
            name=op.f("ck_numeric_facts_gauge_or_abs"),
        ),
        sa.CheckConstraint(
            "quantity IN ('pressure', 'force', 'temperature', 'mass_flow_rate', 'volume_flow_rate', 'power', 'energy', 'voltage', 'current', 'resistance', 'length', 'area', 'volume', 'mass', 'density', 'time', 'frequency', 'velocity', 'acceleration', 'specific_impulse', 'angle', 'ratio', 'valve_state', 'other')",
            name=op.f("ck_numeric_facts_quantity"),
        ),
        sa.CheckConstraint(
            "source IN ('printed', 'ocr', 'vlm', 'table', 'telemetry_stat', 'vendor_claim', 'literature', 'human')",
            name=op.f("ck_numeric_facts_source"),
        ),
        sa.ForeignKeyConstraint(
            ["doc_id"],
            ["documents.doc_id"],
            name=op.f("fk_numeric_facts_doc_id_documents"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["node_id"],
            ["document_nodes.node_id"],
            name=op.f("fk_numeric_facts_node_id_document_nodes"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("fact_id", name=op.f("pk_numeric_facts")),
    )
    op.create_index(op.f("ix_numeric_facts_doc_id"), "numeric_facts", ["doc_id"], unique=False)
    op.create_index(op.f("ix_numeric_facts_node_id"), "numeric_facts", ["node_id"], unique=False)
    op.create_index(
        op.f("ix_numeric_facts_quantity_value_si"), "numeric_facts", ["quantity", "value_si"], unique=False
    )
    for name, column in HNSW_INDEXES:
        op.execute(
            f"CREATE INDEX {name} ON document_nodes USING hnsw ({column} halfvec_cosine_ops) "
            "WITH (m = 16, ef_construction = 128)"
        )


def downgrade() -> None:
    op.drop_index(op.f("ix_numeric_facts_quantity_value_si"), table_name="numeric_facts")
    op.drop_index(op.f("ix_numeric_facts_node_id"), table_name="numeric_facts")
    op.drop_index(op.f("ix_numeric_facts_doc_id"), table_name="numeric_facts")
    op.drop_table("numeric_facts")
    op.drop_index(op.f("ix_entity_mentions_node_id"), table_name="entity_mentions")
    op.drop_index(op.f("ix_entity_mentions_entity_id"), table_name="entity_mentions")
    op.drop_index(op.f("ix_entity_mentions_doc_id"), table_name="entity_mentions")
    op.drop_table("entity_mentions")
    op.drop_index(op.f("ix_entity_aliases_entity_id"), table_name="entity_aliases")
    op.drop_table("entity_aliases")
    op.drop_index(op.f("ix_document_nodes_test_plan_id"), table_name="document_nodes")
    op.drop_index(op.f("ix_document_nodes_source_origin_trust_tier"), table_name="document_nodes")
    op.drop_index(op.f("ix_document_nodes_parent_node_id"), table_name="document_nodes")
    op.drop_index(op.f("ix_document_nodes_node_type"), table_name="document_nodes")
    op.drop_index(
        "ix_document_nodes_needs_review_doc_id",
        table_name="document_nodes",
        postgresql_where=sa.text("needs_review"),
    )
    op.drop_index(op.f("ix_document_nodes_doc_kind"), table_name="document_nodes")
    op.drop_index(op.f("ix_document_nodes_doc_id_ordinal"), table_name="document_nodes")
    op.drop_index(op.f("ix_document_nodes_asset_id"), table_name="document_nodes")
    op.drop_table("document_nodes")
    op.drop_index(op.f("ix_entities_first_seen_doc_id"), table_name="entities")
    op.drop_table("entities")
    op.drop_index(
        "uq_document_sources_primary_per_doc",
        table_name="document_sources",
        postgresql_where=sa.text("role = 'primary'"),
    )
    op.drop_index(
        "uq_document_sources_primary_blob",
        table_name="document_sources",
        postgresql_where=sa.text("role = 'primary'"),
    )
    op.drop_index(op.f("ix_document_sources_blob_sha256"), table_name="document_sources")
    op.drop_table("document_sources")
    op.drop_index(op.f("ix_document_relations_doc_id_b"), table_name="document_relations")
    op.drop_table("document_relations")
    op.drop_index(op.f("ix_assets_blob_sha256"), table_name="assets")
    op.drop_table("assets")
    op.drop_index(op.f("ix_documents_test_run_id"), table_name="documents")
    op.drop_index(op.f("ix_documents_test_plan_id"), table_name="documents")
    op.drop_index(op.f("ix_documents_status"), table_name="documents")
    op.drop_index(op.f("ix_documents_standard_id"), table_name="documents")
    op.drop_index(op.f("ix_documents_source_origin_trust_tier"), table_name="documents")
    op.drop_index(op.f("ix_documents_entity_ids"), table_name="documents", postgresql_using="gin")
    op.drop_index(
        op.f("ix_documents_enrichment"),
        table_name="documents",
        postgresql_using="gin",
        postgresql_ops={"enrichment": "jsonb_path_ops"},
    )
    op.drop_index(op.f("ix_documents_doc_kind_status"), table_name="documents")
    op.drop_table("documents")
    op.drop_index(op.f("ix_audit_events_entity_type_entity_id_at"), table_name="audit_events")
    op.drop_table("audit_events")
