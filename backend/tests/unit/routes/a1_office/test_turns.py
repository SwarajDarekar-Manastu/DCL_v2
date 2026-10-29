"""A large PDF in turns (common/parallel.py): Docling runs of at most 100 pages, each kept as it finishes;
the model's calls side by side; past the turn nothing new starts; an unusable reply leaves the file going."""

import json
import time

import pytest

pytest.importorskip("pypdfium2")

from backend.common.parallel import TurnOver  # noqa: E402
from backend.llm_engine.gemini_types import StructuredOutputError  # noqa: E402
from backend.llm_engine.vision.schemas import PageType, Script  # noqa: E402
from backend.postgres.enums import NodeType  # noqa: E402
from backend.routes.a1_office.convert import OcrPlan, Run, RunResult, plan_runs, saved_runs  # noqa: E402
from backend.routes.a1_office.figures import read_figures  # noqa: E402
from backend.routes.a1_office.tables_qa import check_tables  # noqa: E402
from backend.routes.a1_office.triage import PageDecision  # noqa: E402
from backend.tests.unit.routes.a1_office.test_figures_tables_handwriting import PDF, SPANNED, node  # noqa: E402

SHA = "c" * 64


def page(page_no, engine=None):
    return PageDecision(
        page_no=page_no,
        page_type=PageType.DIGITAL_TEXT,
        language="en",
        script=Script.LATIN,
        is_rotated=False,
        image_only=engine is not None,
        ocr_engine=engine,
    )


def test_a_long_stretch_with_one_plan_is_read_in_runs_of_at_most_100_pages():
    decisions = [page(p) for p in range(1, 251)] + [page(251, "tesseract")]
    assert plan_runs(decisions) == [
        Run(1, 100, None),
        Run(101, 200, None),
        Run(201, 250, None),
        Run(251, 251, OcrPlan("tesseract", ("Latin",))),
    ]


def test_a_finished_run_is_read_back_and_a_new_one_waits_for_the_next_turn():
    kept: dict[str, bytes] = {}
    converted: list[Run] = []

    def convert(pdf, run, name):
        converted.append(run)
        return RunResult(run, {"pages": [run.first, run.last]})

    def runs(deadline=None):
        return saved_runs(
            convert,
            kept.get,
            lambda key, data: kept.setdefault(key, data) and key,
            deadline,
            load=lambda run, data: RunResult(run, json.loads(data)),
            dump=lambda result: json.dumps(result.document).encode(),
        )

    runs()(b"%PDF", Run(1, 100, None))
    late = runs(deadline=time.monotonic() - 1)
    assert late(b"%PDF", Run(1, 100, None)).document == {"pages": [1, 100]}
    with pytest.raises(TurnOver):
        late(b"%PDF", Run(101, 200, OcrPlan("tesseract", ("Latin",))))
    assert (converted, list(kept)) == ([Run(1, 100, None)], ["work/runs/0001-0100-text.json.gz"])


def _unusable(kwargs):
    raise StructuredOutputError("reply does not match the schema", raw_text="{")


def test_an_unusable_table_reply_keeps_tableformers_table_for_a_person(fake_vision):
    result = check_tables(
        [node("tab1", NodeType.TABLE, SPANNED)],
        pdf_bytes=PDF,
        page_ocr={1: 0.6},
        vision=fake_vision(read_table_image=_unusable),
        context="x",
        doc_id=None,
        cloud_allowed=True,
    )
    ((table,), (flag,)) = (result.nodes, result.flags)
    assert (table.content, table.metadata["chosen"], table.metadata["needs_review"]) == (
        SPANNED,
        "tableformer",
        True,
    )
    assert (flag.evidence.table_a_html, flag.evidence.table_b_html) == (SPANNED, None)


def test_past_the_turn_no_table_or_figure_is_sent(fake_vision, memory_store):
    vision = fake_vision()
    late = time.monotonic() - 1
    with pytest.raises(TurnOver):
        check_tables(
            [node("tab1", NodeType.TABLE, SPANNED)],
            pdf_bytes=PDF,
            page_ocr={1: 0.6},
            vision=vision,
            context="x",
            doc_id=None,
            cloud_allowed=True,
            deadline=late,
        )
    with pytest.raises(TurnOver):
        read_figures(
            [node("fig1", NodeType.FIGURE, metadata={"class": "line_chart"})],
            pdf_bytes=PDF,
            blob_sha256=SHA,
            vision=vision,
            context="x",
            doc_id=None,
            cloud_allowed=True,
            put_asset=memory_store("s3://dcl-assets/"),
            deadline=late,
        )
    assert vision.calls == []
