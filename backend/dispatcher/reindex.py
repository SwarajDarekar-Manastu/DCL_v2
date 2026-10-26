"""Run processed files through their route again after the metadata changes (docs/sessions/
PLAN_metadata_search.md step 8): labels from the path, the new piece headers, the file card, run summaries
and question proxies all come from the route and the indexer, and a finished file keeps no route output.

    python -m backend.dispatcher.reindex --route C --limit 5            # relabel all, re-run 5 of route C
    python -m backend.dispatcher.reindex --relabel-only                 # labels and halted cards only
    python -m backend.dispatcher.reindex --route D --stuck --limit 5    # also files stuck in PROCESSING
    python -m backend.dispatcher.reindex --route D --failed             # also FAILED files (gateway outage)
    python -m backend.dispatcher.reindex --route A1 --dry-run
    python -m backend.dispatcher.reindex --route C --doc <doc_id> --doc <doc_id>  # these files, a pilot first

1. Every file's folder context is rebuilt from its stored root, folders, file name and siblings with today's
   patterns (`folder_context.build_folder_context`); an empty plan, run, hardware or date is filled from it.
   A label the route read from the file itself is never replaced.
2. A halted file keeps its status and gets its card (`indexing/card.write_halted_card`).
3. Active files of the route are set PROCESSING and their route task is queued the way the Console's
   "re-process affected documents" does it (`routing.redispatch`). Gemini replies come from the result cache
   when the request is unchanged (the enrichment request does not contain the new header).
"""

import argparse
import logging
import sys
import uuid
from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.dispatcher.contract import DocumentFields
from backend.dispatcher.folder_context import FolderContext, Sibling, build_folder_context
from backend.dispatcher.routing import REPROCESSABLE, Release, redispatch_candidates
from backend.postgres.enums import DocumentStatus, Route, SourceOrigin
from backend.postgres.models import Document

log = logging.getLogger(__name__)


def rebuilt_context(stored: dict) -> FolderContext | None:
    """Today's folder context for a stored one; None when it lacks the path it was built from."""
    if not stored or not stored.get("path_cached") or not stored.get("root_name"):
        return None
    old = FolderContext.model_validate(stored)
    name = old.path_cached.rsplit("/", 1)[-1]
    new = build_folder_context(
        old.root_name,
        old.breadcrumb,
        name,
        [Sibling.model_validate(s) for s in old.siblings],
        root_origin=old.source_origin,
    )
    # the origin and trust a person or rule set stay as they are
    return new.model_copy(update={"source_origin": old.source_origin, "trust_tier": old.trust_tier})


def relabel(document: Document) -> list[str]:
    """Rebuild the folder context and fill the empty labels; returns the columns it filled."""
    context = rebuilt_context(document.folder_context)
    if context is None:
        return []
    document.folder_context = context.model_dump(mode="json")
    filled = []
    for column in ("test_plan_id", "test_run_id", "hardware_item"):
        if getattr(document, column) is None and getattr(context, column) is not None:
            setattr(document, column, getattr(context, column))
            filled.append(column)
    if document.doc_date is None and context.doc_date is not None:
        document.doc_date, document.date_source = context.doc_date, "path"
        filled.append("doc_date")
    return filled


def halted_card(document: Document, embed) -> None:
    from backend.indexing.card import write_halted_card

    fields = DocumentFields(
        title=document.title or "",
        doc_kind=document.doc_kind,
        source_origin=SourceOrigin(document.source_origin) if document.source_origin else None,
        test_plan_id=document.test_plan_id,
        test_run_id=document.test_run_id,
        hardware_item=document.hardware_item,
        doc_date=document.doc_date,
        summary=(document.enrichment or {}).get("doc_summary") or None,
    )
    write_halted_card(document, fields, embed=embed)


def run(
    session: Session,
    route: Route | None,
    limit: int | None,
    dry_run: bool,
    embed,
    stuck: bool = False,
    failed: bool = False,
    docs: Sequence[uuid.UUID] = (),
) -> dict:
    documents = session.scalars(select(Document).where(Document.status != DocumentStatus.DELETED)).all()
    filled: dict[str, int] = {}
    halted = 0
    for document in documents:
        for column in relabel(document):
            filled[column] = filled.get(column, 0) + 1
        if document.status == DocumentStatus.HALTED:
            halted_card(document, None if dry_run else embed)
            halted += 1
    releases: list[Release] = []
    if route is not None:
        from backend.dispatcher.adapters import task_for_route

        found = task_for_route(route)
        statuses = (
            *REPROCESSABLE,
            *((DocumentStatus.PROCESSING,) if stuck else ()),
            *((DocumentStatus.FAILED,) if failed else ()),
        )
        # a file with its new card was re-run already: repeated calls with --limit walk through the rest;
        # named files (--doc) re-run whatever their card, for a pilot after a route change (plan step E)
        found_docs = redispatch_candidates(session, route, statuses)
        pending = (
            [d for d in found_docs if d.doc_id in set(docs)]
            if docs
            else [d for d in found_docs if d.card_embedding is None]
        )
        candidates = pending[: limit or None]
        if found is not None and not dry_run:
            task, queue = found
            for document in candidates:
                document.status = DocumentStatus.PROCESSING
                document.staged_payload_uri = None
                releases.append(Release(doc_id=document.doc_id, task=task, queue=str(queue)))
        planned = len(candidates)
    else:
        planned = 0
    if dry_run:
        session.rollback()
    else:
        session.commit()
    return {"labels_filled": filled, "halted_cards": halted, "queued": len(releases), "planned": planned,
            "left": (len(pending) - planned) if route is not None else 0, "releases": releases}  # fmt: skip


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--route", choices=[r.value for r in Route])
    parser.add_argument("--limit", type=int)
    parser.add_argument("--relabel-only", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--stuck", action="store_true", help="also queue files stuck in PROCESSING")
    parser.add_argument("--failed", action="store_true", help="also queue FAILED files (e.g. gateway outage)")
    parser.add_argument("--doc", action="append", type=uuid.UUID, default=[], help="re-run only this doc_id")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO)
    from backend.celery_redis.tasks_process import enqueue_release
    from backend.indexing.card import models_embedder
    from backend.postgres.session import default_session_factory

    route = None if args.relabel_only or not args.route else Route(args.route)
    with default_session_factory()() as session:
        out = run(
            session,
            route,
            args.limit,
            args.dry_run,
            models_embedder(),
            stuck=args.stuck,
            failed=args.failed,
            docs=args.doc,
        )
    for release in out.pop("releases"):
        enqueue_release(release)
    print(out)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
