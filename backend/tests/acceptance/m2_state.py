"""M2 acceptance state (file 10 §5 M2) and the TP7 footer CONFLICT (file 03 §1.2), read-only.

The database is read in a read-only transaction (``m1_state.read_only``); MinIO objects are only
fetched (GET). Every ``*_violations`` function returns a list of messages, empty when the check passes.
"""

import io
import os
import re
from collections import Counter
from collections.abc import Callable
from pathlib import PurePosixPath
from urllib.parse import urlsplit

import pyarrow.parquet as pq
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.common.units import UnitError, to_canonical
from backend.postgres.enums import DocumentStatus as D
from backend.postgres.enums import FlagSeverity, FlagStatus, FlagType, Route
from backend.postgres.models import (
    Document,
    DocumentSource,
    DriveItem,
    ReviewFlag,
    TelemetryChannel,
    TelemetryRun,
)
from backend.storage.minio import parse_uri

GetObject = Callable[[str], bytes]

# Route C on the stack after S1's live run of 2026-10-22 (STATUS.md): 20 LabJack .dat + 2 TDMS halted.
ROUTE_C_STATUS = {D.HALTED: 22, D.ACTIVE: 7, D.ACTIVE_WITH_SOFT_FLAGS: 11}
COMMITTED_RUNS = {"csv": 1}
SERIES_EXTENSIONS = {".dat", ".tdms"}
OPEN = {FlagStatus.OPEN, FlagStatus.IN_PROGRESS, FlagStatus.REOPENED}
TIME_COLUMNS = {"t_rel_ms", "t_from_ignition_ms"}

# TP7: the folder and file name say Test Plan 7, the scanned sheet's printed footer says Test Plan 6.
TP7_FOLDER_PLAN, TP7_FOOTER_PLAN = "TP07", "TP06"
TP7_FOOTER_LINE = "Test Campaign 2 - Test Plan 6"
FOLDER_SOURCE = re.compile(r"^(folder\[\d+\]|filename)$")


def minio_getter() -> GetObject:
    """GET-only access to the stack's MinIO from DCL_MINIO_ENDPOINT / _ACCESS_KEY / _SECRET_KEY."""
    from minio import Minio

    endpoint = urlsplit(os.environ["DCL_MINIO_ENDPOINT"])
    client = Minio(
        endpoint.netloc,
        access_key=os.environ["DCL_MINIO_ACCESS_KEY"],
        secret_key=os.environ["DCL_MINIO_SECRET_KEY"],
        secure=endpoint.scheme == "https" or os.environ.get("DCL_MINIO_SECURE", "").lower() == "true",
    )

    def get(minio_uri: str) -> bytes:
        response = client.get_object(*parse_uri(minio_uri))
        try:
            return response.read()
        finally:
            response.close()
            response.release_conn()

    return get


# ---------------------------------------------------------------- TP7 footer CONFLICT


def tp7_footer_conflicts(session: Session) -> list[tuple[Document, ReviewFlag]]:
    """A1 documents of the TP07 folder with a test_plan_id CONFLICT naming TP06."""
    return list(
        session.execute(
            select(Document, ReviewFlag)
            .join(ReviewFlag, ReviewFlag.doc_id == Document.doc_id)
            .where(
                Document.route == Route.A1,
                Document.folder_context["test_plan_id"].astext == TP7_FOLDER_PLAN,
                ReviewFlag.flag_type == FlagType.CONFLICT,
                ReviewFlag.evidence["subject"].astext == "test_plan_id",
                ReviewFlag.evidence["b"]["value"].astext == TP7_FOOTER_PLAN,
            )
        ).all()
    )


def tp7_violations(session: Session) -> list[str]:
    found = tp7_footer_conflicts(session)
    if not found:
        return [
            f"no A1 document of a {TP7_FOLDER_PLAN} folder has a test_plan_id CONFLICT naming "
            f"{TP7_FOOTER_PLAN} (has the TP7 sheet gone through Route A1?)"
        ]
    out = []
    for doc, flag in found:
        a, b = flag.evidence.get("a", {}), flag.evidence.get("b", {})
        where = f"doc {doc.doc_id}"
        if flag.severity != FlagSeverity.SOFT:
            out.append(f"{where}: severity {flag.severity}, expected SOFT")
        if doc.test_plan_id != TP7_FOLDER_PLAN:
            out.append(f"{where}: test_plan_id {doc.test_plan_id!r}, the folder value must stay")
        if a.get("value") != TP7_FOLDER_PLAN or not FOLDER_SOURCE.match(a.get("provenance", "")):
            out.append(f"{where}: side a {a!r}, expected {TP7_FOLDER_PLAN} from folder[n] or filename")
        if not b.get("label", "").startswith("page 1 header or footer"):
            out.append(f"{where}: side b label {b.get('label')!r}, expected page-1 furniture")
        if TP7_FOOTER_LINE not in b.get("provenance", ""):
            out.append(f"{where}: page-1 furniture {b.get('provenance')!r} lacks {TP7_FOOTER_LINE!r}")
        if flag.anchor.get("page") != 1:
            out.append(f"{where}: anchor {flag.anchor!r}, expected page 1")
    return out


# ---------------------------------------------------------------- Route C (M2)


def route_c_status_counts(session: Session) -> dict[str, int]:
    rows = session.execute(
        select(Document.status, func.count()).where(Document.route == Route.C).group_by(Document.status)
    ).all()
    return {str(status): n for status, n in rows}


def status_count_violations(counts: dict[str, int]) -> list[str]:
    expected = {str(k): v for k, v in ROUTE_C_STATUS.items()}
    return [
        f"Route C {status}: {counts.get(status, 0)}, expected {expected.get(status, 0)}"
        for status in sorted(set(counts) | set(expected))
        if counts.get(status, 0) != expected.get(status, 0)
    ]


def _open_flags(session: Session) -> dict:
    by_doc: dict = {}
    for doc_id, flag_type, severity in session.execute(
        select(ReviewFlag.doc_id, ReviewFlag.flag_type, ReviewFlag.severity)
        .join(Document, Document.doc_id == ReviewFlag.doc_id)
        .where(Document.route == Route.C, ReviewFlag.status.in_(OPEN))
    ):
        by_doc.setdefault(doc_id, []).append((flag_type, severity))
    return by_doc


def flag_status_violations(session: Session) -> list[str]:
    """File 06: HALTED has an open HARD flag; ACTIVE has no open flag; ACTIVE_WITH_SOFT_FLAGS has open
    SOFT flags only."""
    flags = _open_flags(session)
    out = []
    for doc_id, status in session.execute(
        select(Document.doc_id, Document.status).where(Document.route == Route.C)
    ):
        severities = {s for _, s in flags.get(doc_id, [])}
        ok = {
            D.HALTED: FlagSeverity.HARD in severities,
            D.ACTIVE: not severities,
            D.ACTIVE_WITH_SOFT_FLAGS: severities == {FlagSeverity.SOFT},
        }.get(status, True)
        if not ok:
            out.append(f"doc {doc_id} {status} with open flags {sorted(severities)}")
    return out


def _extension(name: str | None) -> str:
    return PurePosixPath(name or "").suffix.lower()


def series_documents(session: Session) -> dict:
    """Route C documents whose primary file is a .dat or .tdms: doc_id -> status."""
    rows = session.execute(
        select(Document.doc_id, Document.status, DriveItem.name)
        .join(DocumentSource, DocumentSource.doc_id == Document.doc_id)
        .join(DriveItem, DriveItem.blob_sha256 == DocumentSource.blob_sha256)
        .where(Document.route == Route.C, DocumentSource.role == "primary")
    ).all()
    return {doc_id: status for doc_id, status, name in rows if _extension(name) in SERIES_EXTENSIONS}


def unit_case_violations(session: Session, require_suggestion: bool) -> list[str]:
    """M2 criterion 1: every .dat/.tdms document is a committed run or a HALTED UNIT_AMBIGUITY case
    whose evidence shows the operator what to choose from (stated unit, header lines, .cfg scaling or
    sibling units) and, with ``require_suggestion``, a suggested resolution."""
    runs = set(session.scalars(select(TelemetryRun.doc_id)))
    out = []
    for doc_id, status in series_documents(session).items():
        if doc_id in runs:
            continue
        if status != D.HALTED:
            out.append(f"doc {doc_id}: {status} without a telemetry run")
            continue
        cases = session.execute(
            select(ReviewFlag.evidence, ReviewFlag.suggested_resolution).where(
                ReviewFlag.doc_id == doc_id,
                ReviewFlag.flag_type == FlagType.UNIT_AMBIGUITY,
                ReviewFlag.severity == FlagSeverity.HARD,
                ReviewFlag.status.in_(OPEN),
            )
        ).all()
        if not cases:
            out.append(f"doc {doc_id}: HALTED without an open UNIT_AMBIGUITY HARD case")
        for evidence, suggestion in cases:
            evidence = evidence or {}
            channel = evidence.get("channel")
            if not channel or not any(
                evidence.get(k) for k in ("raw_unit", "header_lines", "scaling_equation", "sibling_units")
            ):
                out.append(f"doc {doc_id} channel {channel!r}: no unit evidence to choose from")
            if require_suggestion and not suggestion:
                out.append(f"doc {doc_id} channel {channel!r}: no suggested_resolution")
    return out


def committed_runs(session: Session) -> list[TelemetryRun]:
    return list(session.scalars(select(TelemetryRun).order_by(TelemetryRun.run_label)))


def run_count_violations(runs: list[TelemetryRun]) -> list[str]:
    counts = Counter(str(r.source_format) for r in runs)
    return (
        []
        if counts == Counter(COMMITTED_RUNS)
        else [f"committed runs {dict(counts)}, expected {COMMITTED_RUNS}"]
    )


def _is_canonical(unit: str | None) -> bool:
    if not unit:
        return False
    try:
        value, _ = to_canonical(1.0, unit)
    except UnitError:
        return False
    return abs(value - 1.0) < 1e-12


def si_column_violations(session: Session, runs: list[TelemetryRun], get: GetObject) -> list[str]:
    """M2 criterion 1, committed half: the normalized Parquet has the time columns and one column per
    telemetry_channels row, each in the canonical SI unit of its dimension
    (bar, N, K, g/s, W, else base SI)."""
    out = []
    for run in runs:
        where = f"run {run.run_label}"
        channels = dict(
            session.execute(
                select(TelemetryChannel.canonical_name, TelemetryChannel.unit_si).where(
                    TelemetryChannel.run_uuid == run.run_uuid
                )
            ).all()
        )
        if not channels:
            out.append(f"{where}: no telemetry_channels rows")
        for name, unit in channels.items():
            if not _is_canonical(unit):
                out.append(f"{where}: channel {name} unit_si {unit!r} is not canonical SI")
        if not run.normalized_parquet_uri:
            out.append(f"{where}: no normalized Parquet")
            continue
        schema = pq.read_schema(io.BytesIO(get(run.normalized_parquet_uri)))
        missing = (TIME_COLUMNS | set(channels)) - set(schema.names)
        if missing:
            out.append(f"{where}: Parquet lacks columns {sorted(missing)}")
        for field in schema:
            if field.name in TIME_COLUMNS:
                continue
            unit = (field.metadata or {}).get(b"unit", b"").decode()
            if not _is_canonical(unit):
                out.append(f"{where}: Parquet column {field.name} unit {unit!r} is not canonical SI")
    return out


def duplicate_flag_violations(session: Session) -> list[str]:
    """M2 criterion 6: one flag per (doc_id, fingerprint), whatever the re-index count."""
    rows = session.execute(
        select(ReviewFlag.doc_id, ReviewFlag.fingerprint, func.count())
        .where(ReviewFlag.doc_id.is_not(None))
        .group_by(ReviewFlag.doc_id, ReviewFlag.fingerprint)
        .having(func.count() > 1)
    ).all()
    return [f"doc {d} fingerprint {f}: {n} flags" for d, f, n in rows]
