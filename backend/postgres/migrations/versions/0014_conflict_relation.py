# ruff: noqa: E501, S608  (SQL statements stay on readable lines; the only interpolated text is a constant)
"""CONFLICT evidence gains ``relation`` (sources_disagree, check_failed, note); existing rows are tagged once.

Five producers used the two-sided shape for things that are not two sources disagreeing: the assembler's
notes (side B was a fixed "expected" text), and three failed checks (found against a limit or a rule). Rows
written before this migration carry no ``relation``; this tags them by the labels their producers used.

The assembler's "not included by any master" / "no master found" notes are no longer flags at all: nothing
can be decided about them, and the verdict holds for one folder while the document stands for every copy.
Each open one moves onto its document (``metadata_sources.assembler.notes``) and the flag is deleted; a
document that was soft-flagged only for it returns to ACTIVE. Resolved ones stay as history. Downgrade does
not bring the deleted flags back (the old dispatcher raises them again on the next dispatch).

Revision ID: 0014
Revises: 0013
Create Date: 2026-10-23
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0014"
down_revision: str | None = "0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ORPHAN = (
    "evidence ->> 'kind' = 'conflict' AND evidence -> 'a' ->> 'label' IN ('assembler', 'assembled as') "
    "AND (coalesce(CASE WHEN evidence -> 'a' ->> 'label' = 'assembler' THEN evidence -> 'a' ->> 'value' "
    "ELSE evidence ->> 'subject' END, '') LIKE 'not included by any master%' "
    "OR coalesce(CASE WHEN evidence -> 'a' ->> 'label' = 'assembler' THEN evidence -> 'a' ->> 'value' "
    "ELSE evidence ->> 'subject' END, '') LIKE 'no master found%')"
)
OPEN = "status IN ('OPEN', 'IN_PROGRESS', 'REOPENED')"
CONFLICT = "evidence ->> 'kind' = 'conflict' AND NOT evidence ? 'relation'"

UPGRADE = [
    f"""UPDATE documents SET metadata_sources = jsonb_set(
        coalesce(metadata_sources, '{{}}'::jsonb), '{{assembler}}',
        coalesce(metadata_sources -> 'assembler', '{{}}'::jsonb)
        || jsonb_build_object('notes', coalesce(metadata_sources -> 'assembler' -> 'notes', '[]'::jsonb) || found.notes))
    FROM (SELECT doc_id, jsonb_agg(DISTINCT CASE WHEN evidence -> 'a' ->> 'label' = 'assembler'
                 THEN evidence -> 'a' ->> 'value' ELSE evidence ->> 'subject' END) AS notes
          FROM review_flags WHERE {ORPHAN} AND {OPEN} AND doc_id IS NOT NULL GROUP BY doc_id) AS found
    WHERE documents.doc_id = found.doc_id""",
    f"DELETE FROM review_flags WHERE {ORPHAN} AND {OPEN}",
    """UPDATE documents SET status = 'ACTIVE'
    WHERE status = 'ACTIVE_WITH_SOFT_FLAGS' AND metadata_sources -> 'assembler' ? 'notes'
      AND NOT EXISTS (SELECT 1 FROM review_flags f WHERE f.doc_id = documents.doc_id AND f.severity = 'SOFT'
                      AND f.status IN ('OPEN', 'IN_PROGRESS', 'REOPENED'))""",
    f"""UPDATE review_flags SET evidence = jsonb_set(evidence - 'b', '{{relation}}', '"note"')
    WHERE {CONFLICT} AND evidence -> 'a' ->> 'label' IN ('assembler', 'assembled as')""",
    f"""UPDATE review_flags SET evidence = jsonb_set(evidence, '{{relation}}', '"check_failed"')
    WHERE {CONFLICT} AND (evidence -> 'b' ->> 'label' = 'threshold'
        OR (evidence -> 'a' ->> 'label' IN ('detected', 'cells') AND evidence -> 'b' ->> 'label' = 'expected'))""",
    f"UPDATE review_flags SET evidence = jsonb_set(evidence, '{{relation}}', '\"sources_disagree\"') WHERE {CONFLICT}",
]

DOWNGRADE = [
    """UPDATE review_flags SET evidence = jsonb_set(evidence, '{b}',
        '{"label": "expected", "value": "one unambiguous document", "provenance": "file 03 §1.3", "doc_id": null, "date": null}')
    WHERE evidence ->> 'kind' = 'conflict' AND evidence ->> 'relation' = 'note'""",
    "UPDATE review_flags SET evidence = evidence - 'relation' WHERE evidence ->> 'kind' = 'conflict'",
]


def upgrade() -> None:
    for statement in UPGRADE:
        op.execute(statement)


def downgrade() -> None:
    for statement in DOWNGRADE:
        op.execute(statement)
