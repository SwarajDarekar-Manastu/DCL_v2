"""The gold schema accepts well-formed gold and refuses broken grids and boxes; the local gold (if present)
validates."""

import pytest
from pydantic import ValidationError

from backend.tests.benchmark.gold.gold import DEFAULT_ROOT, GoldTable, Region, load_gold

TABLE = {
    "table_id": "t", "page_id": "p", "source": "x.pdf", "page_no": 1, "bbox": [0.1, 0.1, 0.9, 0.5],
    "tags": ["merged_header"], "n_rows": 2, "n_cols": 2,
    "cells": [{"row": 0, "col": 0, "col_span": 2, "text": "Head", "header": True},
              {"row": 1, "col": 0, "text": "a"}, {"row": 1, "col": 1, "text": "b"}],
}  # fmt: skip


def test_a_merged_header_grid_is_accepted():
    assert GoldTable.model_validate(TABLE).cells[0].col_span == 2


@pytest.mark.parametrize(
    "cells",
    [
        TABLE["cells"][:2],  # a slot left uncovered
        [*TABLE["cells"], {"row": 0, "col": 1, "text": "dup"}],  # a slot covered twice
        [{"row": 0, "col": 0, "col_span": 3, "text": "wide"}, *TABLE["cells"][1:]],  # leaves the grid
    ],
)
def test_broken_grids_are_refused(cells):
    with pytest.raises(ValidationError):
        GoldTable.model_validate({**TABLE, "cells": cells})


@pytest.mark.parametrize("box", [[0.5, 0.1, 0.4, 0.2], [0.1, 0.1, 1.2, 0.2], [0.1, 0.3, 0.2, 0.3]])
def test_boxes_must_be_normalised_and_ordered(box):
    with pytest.raises(ValidationError):
        Region.model_validate({"class": "text", "bbox": box})


def test_local_gold_validates():
    if not (DEFAULT_ROOT / "layout.json").is_file():
        pytest.skip("data/gold is local only")
    gold = load_gold()
    assert gold.pages and gold.tables and gold.equations and gold.handwriting
