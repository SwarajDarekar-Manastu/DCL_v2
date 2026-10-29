"""Route A1 on the shared runner: S2's ``process_office`` (PDF directly; Word family and slides through
LibreOffice, A1.9–A1.10) with the production vision service, the stores under ``{sha}/A1/v1/``,
``critical_field_patterns`` and the per-script OCR engine table from pipeline_config."""

import uuid
from collections.abc import Callable
from typing import Any

from minio import Minio
from sqlalchemy.orm import Session

from backend.dispatcher.contract import ProcessedDocument
from backend.dispatcher.runner import (
    Outcome,
    RunContext,
    common_options,
    file_metadata,
    run_document,
    vision_for,
)
from backend.indexing.commit import Indexer
from backend.postgres import pipeline_config
from backend.postgres.enums import Route

BuildOffice = Callable[..., ProcessedDocument]  # (data, *, session, **process_office options)


def default_build() -> BuildOffice:
    """S2's entry point; Docling is imported only in the parse image."""
    from backend.routes.a1_office.office import process_office

    def build(data: bytes, *, session: Session, file=None, **kwargs: Any) -> ProcessedDocument:
        return process_office(data, vision=vision_for(session, file), **kwargs)

    return build


def process_a1_document(
    session: Session,
    minio: Minio,
    doc_id: uuid.UUID,
    build: BuildOffice,
    indexer: Indexer | None = None,
    deadline: float | None = None,
    turn: int = 0,
) -> Outcome:
    """`deadline`: the end of the task's turn (common/parallel.py). The route keeps what it finished under
    the CIR's `work/`, so the next turn goes on from there; the first turn starts it empty and the route's
    end removes it, so a later run of the file reads it afresh."""
    from backend.routes.a1_office.convert import WORK, convert_run, saved_runs
    from backend.routes.a1_office.route import PARSER_VERSION, Stores

    def a1(ctx: RunContext) -> ProcessedDocument:
        def get_cir(key: str) -> bytes | None:
            return ctx.cir.get(ctx.prefix + key)

        if turn == 0:
            ctx.cir.delete_prefix(ctx.prefix + WORK)
        processed = build(
            ctx.data,
            session=ctx.session,
            file=file_metadata(ctx),
            stores=Stores(put_cir=ctx.put_cir, put_asset=ctx.put_asset, get_cir=get_cir),
            convert=saved_runs(convert_run, get_cir, ctx.put_cir, deadline),
            deadline=deadline,
            folder=ctx.folder,
            critical_field_patterns=tuple(
                pipeline_config.get(ctx.session, "critical_field_patterns", default=[]) or []
            ),
            engine_by_script=pipeline_config.get(ctx.session, "routes.A1.ocr_engine_by_script", default=None),
            enrichment_max=pipeline_config.get(
                ctx.session,
                pipeline_config.FORMULA_ENRICHMENT_MAX,
                default=pipeline_config.FORMULA_ENRICHMENT_DEFAULT,
            ),
            **common_options(ctx),
        )
        ctx.cir.delete_prefix(ctx.prefix + WORK)
        return processed

    return run_document(session, minio, doc_id, Route.A1, PARSER_VERSION, a1, indexer)
