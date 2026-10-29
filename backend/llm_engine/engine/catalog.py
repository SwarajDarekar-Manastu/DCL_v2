"""The catalog step (docs/sessions/PLAN_metadata_search.md step 5, user 2026-10-26): before any model reads
the question, find what it refers to in the metadata of every file, so the question can be reframed with
nothing left open, or the user asked when it can't.

1. `question_labels`: plan, run, hardware and date written in the question (the folder patterns of
   `dispatcher/folder_context.py`) and its identifier tokens.
2. `search_catalog`: files ranked five ways and fused by RRF: the file cards by keyword and by meaning
   (`documents.search_text`, `card_codes`, `card_embedding`; every status, halted included), the pieces by
   meaning and by keyword with their headers (`indexing/retrieval.py` legs, best piece per file), and the
   question's labels. The top files are grouped into subjects: one test (its owner, the plan or else the
   hardware, and its run) or, for a file without labels, its folder.
3. Conflict signals for the ask-back, in code: a run named without plan or hardware that exists under two
   or more owners; several files of the name the question uses in different folders; two subjects close at
   the top.
4. `decide`: after the analysis model reframed the question with these subjects: go on with the chosen
   subjects' files, ask back with the real options, or say the only data is halted.

The conversation's last catalog record (from its trace) carries an open ask-back and the subject chosen, so
an answer like "TP12" resumes the original question and "and the temperature?" stays on the same test.
"""

import json
import re
import uuid
from collections import Counter
from collections.abc import Iterable
from dataclasses import asdict, dataclass, field
from datetime import date
from typing import Any

from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import ARRAY, UUID
from sqlalchemy.orm import Session
from sqlalchemy.types import Date, Text

from backend.dispatcher.folder_context import HARDWARE_PATTERNS, PLAN_PATTERNS, RUN_PATTERNS, path_date
from backend.indexing.identifiers import extract_identifiers
from backend.indexing.retrieval import Scope, SearchFilters, build_where, dense_leg, lexical_leg, rrf
from backend.llm_engine.engine.answer_routes import AnswerRoute, of_document
from backend.llm_engine.engine.tools import Source, ToolResult, provenance_of

STATUSES = ("ACTIVE", "ACTIVE_WITH_SOFT_FLAGS", "HALTED", "PROCESSING")
VISIBLE = ("ACTIVE", "ACTIVE_WITH_SOFT_FLAGS", "PROCESSING")
LEG_LIMIT = 40
TOP_FILES = 15
TOP_SUBJECTS = 6
CLOSE = 0.9  # second subject within 10 % of the first
ASSUMED = "Assumed:"  # how the assumption for an ambiguous question starts (the answer leads with it)
MAX_OPTIONS = 10
MAX_SUBJECT_FILES = 400
MEASURED = frozenset({"telemetry_metric", "run_comparison", str(AnswerRoute.MEASURED)})  # intents or route
MONTHS = {m: i for i, m in enumerate("jan feb mar apr may jun jul aug sep oct nov dec".split(), start=1)}
SPOKEN_DATE = re.compile(
    r"(?i)(?<!\d)(\d{1,2})\s+(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?,?\s+(20\d{2})"
)
WORDS = re.compile(r"[^0-9a-z]+")
ORDINALS = {"first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5, "sixth": 6, "last": -1}


def _norm(value: str) -> str:
    return " ".join(WORDS.split(value.casefold())).strip()


# ---------------------------------------------------------------- labels in the question


@dataclass
class Labels:
    plans: list[str] = field(default_factory=list)
    runs: list[str] = field(default_factory=list)
    hardware: list[str] = field(default_factory=list)
    dates: list[date] = field(default_factory=list)
    codes: list[str] = field(default_factory=list)

    @property
    def named(self) -> bool:
        return bool(self.plans or self.runs or self.hardware or self.dates)


def _found(patterns, question: str, fmt) -> list[str]:
    return list(dict.fromkeys(fmt(m.group(1)) for p in patterns for m in p.finditer(question)))


def question_labels(question: str) -> Labels:
    plans = _found(PLAN_PATTERNS, question, lambda n: f"TP{int(n):02d}")
    hardware = _found(HARDWARE_PATTERNS, question, lambda n: f"INJ{int(n):02d}")
    # "Test Plan 12" is a plan, not run 12: read runs with the plan phrases taken out
    rest = question
    for pattern in PLAN_PATTERNS:
        rest = pattern.sub(" ", rest)
    runs = _found(RUN_PATTERNS, rest, lambda n: f"T{int(n):02d}")
    dates = [d for d in [path_date(question)] if d]
    for day, month, year in SPOKEN_DATE.findall(question):
        try:
            dates.append(date(int(year), MONTHS[month.casefold()[:3]], int(day)))
        except ValueError:
            pass
    return Labels(plans, runs, hardware, list(dict.fromkeys(dates)), extract_identifiers(question))


# ---------------------------------------------------------------- files, subjects, the result


@dataclass
class CatalogFile:
    doc_id: str
    title: str
    doc_kind: str
    status: str
    route: str | None
    doc_date: str | None
    test_plan_id: str | None
    test_run_id: str | None
    hardware_item: str | None
    folder: str
    summary: str
    card: str
    source_origin: str | None
    folder_kind: str | None = None
    case_keys: list[str] = field(default_factory=list)
    run_labels: list[str] = field(default_factory=list)
    best_piece: str | None = None
    score: float = 0.0

    @property
    def owner(self) -> str | None:
        """What a test run belongs to: its test plan, else its hardware (Injector 14 runs have no plan)."""
        return self.test_plan_id or self.hardware_item

    def line(self) -> str:
        route = of_document(self.route, self.doc_kind, self.folder_kind)
        bits = [
            self.doc_kind,
            f"route {route}" if route else None,
            self.doc_date,
            self.status if self.status != "ACTIVE" else None,
        ]
        if self.case_keys:
            bits.append("review case " + ", ".join(_case(c) for c in self.case_keys))
        where = f" in {self.folder}" if self.folder else ""
        return f"{self.title} ({', '.join(b for b in bits if b)}){where}"


@dataclass
class Subject:
    id: str
    owner: str | None
    run: str | None
    folder: str | None
    files: list[CatalogFile]
    score: float

    @property
    def label(self) -> str:
        if self.owner or self.run:
            run = f"Test {self.run[1:]}" if self.run and self.run.startswith("T") else self.run
            return " · ".join(x for x in (self.owner, run) if x)
        return self.folder or "unlabelled files"

    def describe(self) -> str:
        held = [f for f in self.files if f.status == "HALTED"]
        text = f"{self.label}: " + _kinds(self.files)
        if held:
            cases = sorted({_case(c) for f in held for c in f.case_keys})
            text += f"; {len(held)} halted for review" + (f" (case {', '.join(cases)})" if cases else "")
        return text


@dataclass
class Option:
    id: str
    label: str
    owner: str | None
    run: str | None
    folder: str | None
    doc_ids: list[str]


@dataclass
class CatalogResult:
    question: str
    labels: Labels
    subjects: list[Subject]
    conflicts: list[str]
    options: list[Option]
    previous: dict | None = None

    def prompt_text(self) -> str:
        """What the analysis model reads as `$catalog`."""
        if not self.subjects:
            return "Nothing in the team's files matches the question's terms."
        lines = []
        for s in self.subjects:
            lines.append(f"{s.id} {s.describe()}")
            for f in s.files[:4]:
                summary = f" — {f.summary[:200]}" if f.summary else ""
                where = f" [matched in: {f.best_piece}]" if f.best_piece else ""
                lines.append(f"   - {f.line()}{summary}{where}")
        if self.conflicts:
            lines.append("Conflicts: " + " ".join(self.conflicts))
        return "\n".join(lines)


def _execute(session: Session, sql: str, params: dict, *binds):
    return session.execute(text(sql).bindparams(*binds), params).all()


def _bm25_files(session: Session, query: str, codes: list[str]) -> list[str]:
    matches = ["search_text ||| :q", "title ||| :q"]
    params: dict[str, Any] = {"q": query, "statuses": list(STATUSES), "limit": LEG_LIMIT}
    if codes:
        matches.append("card_codes ||| :codes")
        params["codes"] = " ".join(codes)
    rows = _execute(
        session,
        "SELECT doc_id, pdb.score(doc_id) AS score FROM documents "  # noqa: S608 (constant fragments)
        f"WHERE ({' OR '.join(matches)}) AND status = ANY(:statuses) ORDER BY score DESC LIMIT :limit",
        params,
        bindparam("statuses", type_=ARRAY(Text)),
    )
    return [str(r[0]) for r in rows]


def _dense_files(session: Session, vector: list[float]) -> list[str]:
    q = "[" + ",".join(f"{x:.6f}" for x in vector) + "]"
    rows = _execute(
        session,
        "SELECT doc_id FROM documents WHERE card_embedding IS NOT NULL AND status = ANY(:statuses) "
        "ORDER BY card_embedding <=> CAST(:q AS halfvec(768)) LIMIT :limit",
        {"q": q, "statuses": list(STATUSES), "limit": LEG_LIMIT},
        bindparam("statuses", type_=ARRAY(Text)),
    )
    return [str(r[0]) for r in rows]


def _piece_files(session: Session, query: str, vector: list[float], codes: list[str]):
    """Files by their best piece, by meaning and by keyword (the piece headers are in the keyword index)."""
    where = build_where(SearchFilters(), Scope.CHILD)
    dense, _ = dense_leg(session, vector, where)
    lexical = lexical_leg(session, query, codes, ["en"], where)
    ids = list(dict.fromkeys([*dense, *lexical]))
    rows = (
        _execute(
            session,
            "SELECT node_id, doc_id, breadcrumb, node_type FROM document_nodes WHERE node_id = ANY(:ids)",
            {"ids": ids},
            bindparam("ids", type_=ARRAY(UUID(as_uuid=True))),
        )
        if ids
        else []
    )
    by_node = {r.node_id: r for r in rows}
    best: dict[str, str] = {}

    def files(ranking: list[uuid.UUID]) -> list[str]:
        out: list[str] = []
        for node_id in ranking:
            row = by_node.get(node_id)
            if row is None:
                continue
            doc = str(row.doc_id)
            if doc not in out:
                out.append(doc)
                best.setdefault(doc, f"{str(row.node_type).replace('_', ' ')}: {row.breadcrumb or ''}"[:160])
        return out

    return files(dense), files(lexical), best


def _label_files(session: Session, labels: Labels) -> list[str]:
    if not labels.named:
        return []
    rows = _execute(
        session,
        "SELECT doc_id FROM documents WHERE status = ANY(:statuses) AND ("
        "test_plan_id = ANY(:plans) OR test_run_id = ANY(:runs) OR hardware_item = ANY(:hw) OR "
        "doc_date = ANY(:dates)) ORDER BY (coalesce((test_plan_id = ANY(:plans))::int, 0) + "
        "coalesce((test_run_id = ANY(:runs))::int, 0) + coalesce((hardware_item = ANY(:hw))::int, 0) + "
        "coalesce((doc_date = ANY(:dates))::int, 0)) DESC NULLS LAST, doc_date DESC NULLS LAST LIMIT :limit",
        {
            "statuses": list(STATUSES),
            "plans": labels.plans,
            "runs": labels.runs,
            "hw": labels.hardware,
            "dates": labels.dates,
            "limit": LEG_LIMIT,
        },
        bindparam("statuses", type_=ARRAY(Text)),
        bindparam("plans", type_=ARRAY(Text)),
        bindparam("runs", type_=ARRAY(Text)),
        bindparam("hw", type_=ARRAY(Text)),
        bindparam("dates", type_=ARRAY(Date)),
    )
    return [str(r[0]) for r in rows]


FILE_SQL = (
    "SELECT d.doc_id, d.title, d.doc_kind, d.status, d.route, d.doc_date, d.test_plan_id, d.test_run_id, "
    "d.hardware_item, d.source_origin, d.folder_context -> 'breadcrumb' AS crumbs, "
    "d.folder_context ->> 'folder_kind' AS folder_kind, "
    "coalesce(d.search_text, d.title) AS card, coalesce(d.enrichment ->> 'doc_summary', '') AS summary, "
    "(SELECT array_agg(DISTINCT f.case_key) FROM review_flags f WHERE f.doc_id = d.doc_id "
    " AND f.status = 'OPEN' AND f.severity = 'HARD') AS case_keys, "
    "(SELECT array_agg(r.run_label ORDER BY r.run_label) FROM telemetry_runs r WHERE r.doc_id = d.doc_id) "
    " AS run_labels FROM documents d WHERE "
)


def _files(session: Session, where: str, params: dict, *binds) -> list[CatalogFile]:
    rows = _execute(session, FILE_SQL + where, params, *binds)
    out = []
    for r in rows:
        held = r.status == "HALTED" and r.test_run_id
        owner = r.test_plan_id or r.hardware_item
        out.append(
            CatalogFile(
                doc_id=str(r.doc_id),
                title=r.title or "",
                doc_kind=r.doc_kind,
                status=r.status,
                route=r.route,
                doc_date=r.doc_date.isoformat() if r.doc_date else None,
                test_plan_id=r.test_plan_id,
                test_run_id=r.test_run_id,
                hardware_item=r.hardware_item,
                folder=" › ".join(r.crumbs or []),
                summary=" ".join((r.summary or "").split())[:600],
                card=r.card or "",
                source_origin=r.source_origin,
                folder_kind=r.folder_kind,
                case_keys=list(r.case_keys or []),
                # a halted run was never committed: its label is the one its commit would write
                run_labels=list(r.run_labels or [])
                or ([f"{owner}_{r.test_run_id}"] if held and owner else []),
            )
        )
    return out


def files_by_id(session: Session, doc_ids: list[str]) -> list[CatalogFile]:
    if not doc_ids:
        return []
    found = {
        f.doc_id: f
        for f in _files(
            session,
            "d.doc_id = ANY(:ids)",
            {"ids": [uuid.UUID(d) for d in doc_ids]},
            bindparam("ids", type_=ARRAY(UUID(as_uuid=True))),
        )
    }
    return [found[d] for d in doc_ids if d in found]


def subject_files(
    session: Session, owner: str | None, run: str | None, folder: str | None
) -> list[CatalogFile]:
    """Every file of a subject, not only the top ones: the owner's files of that run plus the owner's files
    with no run (the test report of the plan); for an unlabelled subject, the files of its folder."""
    if owner:
        where = (
            "coalesce(d.test_plan_id, d.hardware_item) = :owner AND d.status = ANY(:statuses) "
            "AND (CAST(:run AS text) IS NULL OR d.test_run_id IS NULL OR d.test_run_id = :run) LIMIT :limit"
        )
        params = {"owner": owner, "run": run, "statuses": list(STATUSES), "limit": MAX_SUBJECT_FILES}
    elif run:
        where = "d.test_run_id = :run AND d.status = ANY(:statuses) LIMIT :limit"
        params = {"run": run, "statuses": list(STATUSES), "limit": MAX_SUBJECT_FILES}
    else:
        crumbs = (folder or "").split(" › ")
        where = (
            "d.folder_context -> 'breadcrumb' = CAST(:crumbs AS jsonb) AND d.status = ANY(:statuses) "
            "LIMIT :limit"
        )
        params = {"crumbs": json.dumps(crumbs), "statuses": list(STATUSES), "limit": MAX_SUBJECT_FILES}
    return _files(session, where, params, bindparam("statuses", type_=ARRAY(Text)))


def _key(f: CatalogFile) -> tuple[str | None, str | None, str | None]:
    if f.owner or f.test_run_id:
        return f.owner, f.test_run_id, None
    return None, None, f.folder


def group(files: list[CatalogFile]) -> list[Subject]:
    groups: dict[tuple, list[CatalogFile]] = {}
    for f in files:
        groups.setdefault(_key(f), []).append(f)
    subjects = [
        Subject("", owner, run, folder, members, max(m.score for m in members))
        for (owner, run, folder), members in groups.items()
    ]
    subjects.sort(key=lambda s: s.score, reverse=True)
    for n, s in enumerate(subjects, start=1):
        s.id = f"S{n}"
    return subjects


# ---------------------------------------------------------------- conflict signals


def _run_conflict(session: Session, labels: Labels) -> list[Option]:
    """A run named without its plan or hardware that exists under two or more owners: one option per owner."""
    if not labels.runs or labels.plans or labels.hardware:
        return []
    rows = _execute(
        session,
        "SELECT coalesce(test_plan_id, hardware_item) AS owner, test_run_id, array_agg(doc_id::text) AS docs "
        "FROM documents WHERE test_run_id = ANY(:runs) AND status = ANY(:statuses) "
        "AND coalesce(test_plan_id, hardware_item) IS NOT NULL GROUP BY 1, 2 ORDER BY 1, 2",
        {"runs": labels.runs, "statuses": list(STATUSES)},
        bindparam("runs", type_=ARRAY(Text)),
        bindparam("statuses", type_=ARRAY(Text)),
    )
    if len({r.owner for r in rows}) < 2:
        return []
    return [Option("", "", r.owner, r.test_run_id, None, list(r.docs)) for r in rows]


FILE_WORDS = frozenset(
    "photo photos picture pictures image images report reports video videos clip plot plots graph chart "
    "sheet sheets workbook file files drawing drawings diagram diagrams schematic document documents".split()
)


def _name(title: str) -> str:
    """A file's name as people say it: normalized, without a leading number ("03 VF Gasket" → "vf gasket")."""
    return re.sub(r"^(?:\d+ )+", "", _norm(title))


def _named(name: str, asked: str) -> bool:
    """The question uses this file name; a one-word name only with a word for the kind of file ("photo")."""
    return len(name) >= 3 and f" {name} " in asked and (" " in name or bool(set(asked.split()) & FILE_WORDS))


def same_name_options(files: list[CatalogFile], question: str, labels: Labels) -> tuple[str, list[Option]]:
    """Of the files whose name the question uses, those in different folders that the question's labels and
    folder words don't tell apart: one option per file. The most specific (longest) name is tried first."""
    asked = f" {_norm(question)} "
    by_name: dict[str, list[CatalogFile]] = {}
    for f in files:
        if _named(name := _name(f.title), asked):
            by_name.setdefault(name, []).append(f)
    # "thruster" inside "thruster configuration": the question names the longer file, not every "Thruster"
    names = [n for n in by_name if not any(n != m and f" {n} " in f" {m} " for m in by_name)]
    for name in sorted(names, key=len, reverse=True):
        same = [
            f
            for f in by_name[name]
            if (not labels.plans or f.test_plan_id in labels.plans)
            and (not labels.hardware or f.hardware_item in labels.hardware)
            and (not labels.runs or f.test_run_id in labels.runs)
        ]

        def told(f: CatalogFile) -> int:
            """The longest folder name of the file the question uses: "de-integration" beats "integration"."""
            words = [_norm(part) for part in f.folder.split(" › ")[1:]]
            return max((len(w) for w in words if w and f" {w} " in asked), default=0)

        best = max((told(f) for f in same), default=0)
        same = [f for f in same if told(f) == best]
        if len({f.folder for f in same}) >= 2:
            same.sort(key=lambda f: (f.owner or "", f.folder))
            return same[0].title, [Option("", "", f.owner, f.test_run_id, f.folder, [f.doc_id]) for f in same]
    return "", []


def _same_name(session: Session, question: str, labels: Labels) -> tuple[str, list[Option]]:
    """`same_name_options` over every file in the index whose name the question uses (not only the top)."""
    asked = f" {_norm(question)} "
    rows = _execute(
        session,
        "SELECT doc_id::text AS doc_id, title FROM documents WHERE status = ANY(:statuses)",
        {"statuses": list(STATUSES)},
        bindparam("statuses", type_=ARRAY(Text)),
    )
    ids = [r.doc_id for r in rows if _named(_name(r.title or ""), asked)]
    return same_name_options(files_by_id(session, ids), question, labels)


def _kinds(members: list[CatalogFile]) -> str:
    """'2 hardware photos, 1 engineering table'; a file the route could not type is a 'file'."""
    counts = Counter("file" if m.doc_kind == "unknown" else m.doc_kind.replace("_", " ") for m in members)
    return ", ".join(f"{n} {k}{'s' if n > 1 else ''}" for k, n in counts.most_common(3))


def _case(key: str) -> str:
    """A review case key (`<doc id>:<n>`) as a short reference."""
    head, _, tail = key.partition(":")
    return head[:8] + (f":{tail}" if tail else "")


def _label_option(option: Option, files: dict[str, CatalogFile]) -> str:
    members = [files[d] for d in option.doc_ids if d in files]
    head = " · ".join(x for x in (option.owner, option.run and f"Test {option.run[1:]}") if x)
    if option.folder:
        head = " › ".join(x for x in (head, option.folder.split(" › ")[-1]) if x)
    if members:
        what = _kinds(members)
        dates = sorted({m.doc_date for m in members if m.doc_date})
        held = sorted({_case(c) for m in members if m.status == "HALTED" for c in m.case_keys})
        what += f", {dates[0]}" if dates else ""
        if any(m.status == "HALTED" for m in members):
            what += " — halted for unit review" + (f" (case {', '.join(held)})" if held else "")
        return f"{head}: {what}"
    return head


# ---------------------------------------------------------------- the search


def search_catalog(
    session: Session,
    question: str,
    vector: list[float],
    previous: dict | None = None,
) -> CatalogResult:
    labels = question_labels(question)
    chosen = (previous or {}).get("chosen") or {}
    if labels.runs and not (labels.plans or labels.hardware) and chosen.get("owner"):
        # "and test 5?" after TP12 Test 04: the conversation names the owner the question leaves out
        (labels.plans if chosen["owner"].startswith("TP") else labels.hardware).append(chosen["owner"])
    piece_dense, piece_lexical, best = _piece_files(session, question, vector, labels.codes)
    rankings = [
        _bm25_files(session, question, labels.codes),
        _dense_files(session, vector),
        piece_dense,
        piece_lexical,
        _label_files(session, labels),
    ]
    scores = rrf(rankings)
    top = sorted(scores, key=lambda d: scores[d], reverse=True)[:TOP_FILES]
    files = files_by_id(session, top)
    for f in files:
        f.score, f.best_piece = scores[f.doc_id], best.get(f.doc_id)
    subjects = group(files)[:TOP_SUBJECTS]
    if (
        chosen and not labels.named
    ):  # a follow-up that names nothing new may stay on the conversation's subject
        subjects.insert(
            0, Subject("S0", chosen.get("owner"), chosen.get("run"), chosen.get("folder"), [], 0.0)
        )

    conflicts, options = [], _run_conflict(session, labels)
    if options:
        owners = ", ".join(sorted({o.owner for o in options if o.owner}))
        conflicts.append(
            f"Run {', '.join(labels.runs)} exists under {owners} and the question names neither."
        )
    else:
        title, options = _same_name(session, question, labels)
        if options:
            conflicts.append(f"{len(options)} files named '{title}' sit in different folders.")
    if len(subjects) >= 2 and subjects[1].score >= CLOSE * subjects[0].score:
        conflicts.append(f"{subjects[0].id} and {subjects[1].id} fit about equally well.")
    if labels.named and not rankings[4]:
        named = ", ".join([*labels.plans, *labels.runs, *labels.hardware, *map(str, labels.dates)])
        conflicts.append(f"Nothing in the files is labelled {named}.")
    if options:
        known = {f.doc_id: f for f in files}
        missing = [d for o in options for d in o.doc_ids if d not in known]
        known |= {f.doc_id: f for f in files_by_id(session, missing)}
        for n, option in enumerate(options[:MAX_OPTIONS], start=1):
            option.id, option.label = str(n), _label_option(option, known)
        options = options[:MAX_OPTIONS]
    return CatalogResult(question, labels, subjects, [c for c in conflicts if c], options, previous)


# ---------------------------------------------------------------- the conversation's last catalog record


def previous_record(session: Session, chat_id: str | None, user_id: str | None) -> dict | None:
    """The catalog record of this chat's last answer (``answer_traces.query_analysis.catalog``)."""
    if not chat_id:
        return None
    rows = _execute(
        session,
        "SELECT query_analysis -> 'catalog' AS catalog, user_id FROM answer_traces WHERE chat_id = :chat "
        "ORDER BY created_at DESC LIMIT 1",
        {"chat": chat_id},
    )
    if not rows or not rows[0].catalog or (rows[0].user_id and user_id and rows[0].user_id != user_id):
        return None
    return dict(rows[0].catalog)


def chosen_option(previous: dict | None, message: str) -> dict | None:
    """The option an answer to an open ask-back picks: its number, an ordinal word, or words of its label."""
    options = ((previous or {}).get("ask") or {}).get("options") or []
    if not options:
        return None
    said = f" {_norm(message)} "
    for word, n in ORDINALS.items():
        if f" {word} " in said:
            return options[n - 1] if n > 0 and n <= len(options) else options[-1] if n < 0 else None
    numbers = re.findall(r"(?<![\w.])(\d)(?![\w.])", message)
    if len(numbers) == 1 and 1 <= int(numbers[0]) <= len(options) and len(message.split()) <= 3:
        return options[int(numbers[0]) - 1]
    labels = question_labels(message)

    def fit(option: dict) -> int:
        """How well the answer names the option: its owner, else the longest of its folder words it uses
        ("the de-integration one" fits "De-Integration" better than "Integration")."""
        if option.get("owner") and option["owner"] in [*labels.plans, *labels.hardware]:
            score = 1000
        else:
            score = 0
        folder = _norm((option.get("folder") or "").split(" › ")[-1])
        return score + (len(folder) if folder and f" {folder} " in said else 0)

    scores = [fit(o) for o in options]
    best = max(scores)
    picked = [o for o, s in zip(options, scores, strict=True) if s == best and s > 0]
    return picked[0] if len(picked) == 1 else None


# ---------------------------------------------------------------- the decision after the analysis


@dataclass
class Decision:
    kind: str  # "go", "ask", "halted"
    text: str = ""
    doc_ids: list[str] = field(default_factory=list)
    run_labels: list[str] = field(default_factory=list)
    subject: dict | None = None
    caveats: list[str] = field(default_factory=list)
    pinned: bool = False  # the user typed or picked the subject: its files are the only ones searched

    def record(self, catalog: CatalogResult, question: str) -> dict:
        """What the trace keeps for the next turn (and the Console shows)."""
        return {
            "question": question,
            "decision": self.kind,
            "subjects": [{"id": s.id, "label": s.label, "files": len(s.files)} for s in catalog.subjects],
            "conflicts": catalog.conflicts,
            "chosen": self.subject,
            "doc_ids": self.doc_ids[:MAX_SUBJECT_FILES],
            "pinned": self.pinned,
            "run_labels": self.run_labels,
            "ask": {"question": question, "options": [asdict(o) for o in catalog.options]}
            if self.kind == "ask"
            else None,
        }


def ask_text(question: str, options: list[Option] | list[dict]) -> str:
    lines = [f"Your question can mean more than one thing in our files: “{question}”. Which one do you mean?"]
    for o in options:
        o = o if isinstance(o, dict) else asdict(o)
        lines.append(f"{o['id']}. {o['label']}")
    lines.append("Reply with the number or name it (for example the test plan).")
    return "\n".join(lines)


def _subject_dict(owner, run, folder, label) -> dict:
    return {"owner": owner, "run": run, "folder": folder, "label": label}


def _typed(subject: Subject, labels: Labels) -> int:
    """How many of this subject's labels (its plan or hardware, its run) the question names."""
    return bool(subject.owner and subject.owner in [*labels.plans, *labels.hardware]) + bool(
        subject.run and subject.run in labels.runs
    )


def _likeliest(catalog: CatalogResult) -> list[Subject]:
    """The top subject, or the top two when they fit about equally well (PLAN_query_routing.md step 1)."""
    found = [s for s in catalog.subjects if s.id != "S0"]
    tied = len(found) >= 2 and found[1].score >= CLOSE * found[0].score
    return found[: 2 if tied else 1]


def _assumption(picked: list[Subject], catalog: CatalogResult) -> str:
    """What the answer states it assumed: the subjects it goes on with and up to three others that fit."""

    def name(s: Subject) -> str:
        return s.label.split(" › ")[-1]  # a folder subject by its own folder name

    others = [name(s) for s in catalog.subjects if s.id != "S0" and s not in picked][:3]
    note = f"{ASSUMED} the question is about {' and '.join(name(s) for s in picked)}"
    return note + (f"; other matches: {', '.join(others)}." if others else ".")


def decide(
    session: Session,
    catalog: CatalogResult,
    *,
    resolution: str,
    subject_ids: list[str],
    intents: Iterable[str],
    forced: dict | None = None,
) -> Decision:
    """Go on, ask back or report halted data. `forced` is the option or subject the conversation settled.

    Only the code signals ask back (a run under two owners, a named file in two folders: `catalog.options`).
    A question the model finds ambiguous goes on with the likeliest subject and says so (PLAN_query_routing.md
    step 1). The subject's files are the only ones searched when the user typed or picked it; otherwise they
    are ranked higher (`Decision.pinned`)."""
    caveats: list[str] = []
    if forced is not None:
        chosen, pinned = [forced], True
    else:
        if catalog.options:
            return Decision("ask", ask_text(catalog.question, catalog.options))
        picked = [s for s in catalog.subjects if s.id in subject_ids]
        labels = catalog.labels
        if not picked and labels.named and catalog.subjects:
            named = sorted(
                (s for s in catalog.subjects if _typed(s, labels)), key=lambda s: -_typed(s, labels)
            )
            picked = named[:1]
        if not picked and resolution == "ambiguous":
            picked = _likeliest(catalog)
        if not picked:
            return Decision("go", caveats=[c for c in catalog.conflicts if c.startswith("Nothing")])
        chosen = [_subject_dict(s.owner, s.run, s.folder, s.label) for s in picked]
        pinned = all(_typed(s, labels) for s in picked)
        if resolution == "ambiguous" and not pinned:  # whoever picked them, the answer says what it assumed
            caveats = [_assumption(picked, catalog)]
    files: list[CatalogFile] = []
    for c in chosen:
        if c.get("doc_ids") and c.get("folder"):  # one file or one folder's files the user picked
            files += files_by_id(session, list(c["doc_ids"]))
        else:
            files += subject_files(session, c.get("owner"), c.get("run"), c.get("folder"))
    ranked = {f.doc_id: n for n, f in enumerate(f for s in catalog.subjects for f in s.files)}
    files = sorted({f.doc_id: f for f in files}.values(), key=lambda f: ranked.get(f.doc_id, len(ranked)))
    subject = chosen[0] if len(chosen) == 1 else {"label": "; ".join(c["label"] for c in chosen)}
    runs = [r for f in files if f.status != "HALTED" for r in f.run_labels]
    if set(intents) & MEASURED:
        measured = [f for f in files if f.doc_kind == "telemetry_run"]
        if measured and all(f.status == "HALTED" for f in measured):
            cases = sorted({_case(c) for f in measured for c in f.case_keys})
            text = (
                f"The measured data for {subject['label']} exists "
                f"({', '.join(f.title for f in measured[:6])}) but is halted for review before it can be "
                "used: its channel units are waiting for a person's decision"
                + (f" (review case {', '.join(cases)})" if cases else "")
                + ". I can't give a measured value until that review is done."
            )
            return Decision("halted", text, [f.doc_id for f in files], [], subject, caveats, pinned)
    return Decision("go", "", [f.doc_id for f in files], runs, subject, caveats, pinned)


def catalog_evidence(session: Session, doc_ids: list[str], limit: int = 8) -> ToolResult | None:
    """The chosen files' cards as file-level evidence for the writer and the checker."""
    files = files_by_id(session, doc_ids[:limit])
    if not files:
        return None
    hits = [{"title": f.title, "parent_text": f.card, "breadcrumb": f.folder, "page_no": None} for f in files]
    sources = [
        Source(
            doc_id=uuid.UUID(f.doc_id),
            title=f.title,
            label=f.title,
            provenance=provenance_of(f.source_origin, f.doc_kind),
        )
        for f in files
    ]
    display = "Files:\n" + "\n".join(f"- {f.line()}" for f in files)
    return ToolResult(tool="catalog", result={"hits": hits}, provenance=sources, display=display)


def reframing_ok(reframed: str, allowed_text: str) -> bool:
    """A reframed question may only name identifiers the question, the conversation or the catalog hold."""
    allowed = set(extract_identifiers(allowed_text))
    return all(code in allowed for code in extract_identifiers(reframed))
