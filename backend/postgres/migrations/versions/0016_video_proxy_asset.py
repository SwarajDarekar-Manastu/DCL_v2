# ruff: noqa: E501  (literal CHECK value lists stay on one line each)
"""Asset kind ``video_proxy``: the compressed copy of a video that Route F processes and the viewer plays.

The original blob in ``dcl-raw`` stays the source of truth; the copy is a rendering, so it lives in
``dcl-assets`` like keyframes and page renders (user, 2026-10-24).

Revision ID: 0016
Revises: 0015
Create Date: 2026-10-24
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0016"
down_revision: str | None = "0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OLD = "kind IN ('page_render', 'figure_crop', 'handwriting_crop', 'table_crop', 'photo_web', 'photo_thumb', 'photo_in_doc', 'video_frame', 'diagram_render', 'sparkline')"
NEW = "kind IN ('page_render', 'figure_crop', 'handwriting_crop', 'table_crop', 'photo_web', 'photo_thumb', 'photo_in_doc', 'video_frame', 'video_proxy', 'diagram_render', 'sparkline')"


def upgrade() -> None:
    op.drop_constraint(op.f("ck_assets_kind"), "assets", type_="check")
    op.create_check_constraint(op.f("ck_assets_kind"), "assets", NEW)


def downgrade() -> None:
    op.execute("DELETE FROM assets WHERE kind = 'video_proxy'")
    op.drop_constraint(op.f("ck_assets_kind"), "assets", type_="check")
    op.create_check_constraint(op.f("ck_assets_kind"), "assets", OLD)
