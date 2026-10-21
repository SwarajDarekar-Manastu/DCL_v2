import math

import pytest

from backend.llm_engine import local_models
from backend.llm_engine.local_models import EmbedKind, InputTooLong, rank_scores, resolve_dtype

pytest.importorskip("torch")  # default unit suite runs without GPU libraries (S2: fake-backend path for CI)


@pytest.mark.parametrize("name", ["float16", "half", "fp16", "int8"])
def test_resolve_dtype_refuses_everything_but_bfloat16_and_float32(name):
    with pytest.raises(ValueError, match="bfloat16 or float32"):
        resolve_dtype(name, "cpu")


def test_resolve_dtype_accepts_float32():
    import torch

    assert resolve_dtype("float32", "cpu") is torch.float32


def test_load_models_refuses_float16_before_loading_any_weights(monkeypatch):
    monkeypatch.setattr(local_models, "_models", None)
    with pytest.raises(ValueError, match="float16"):
        local_models.load_models(device="cpu", dtype="float16")
    assert local_models._models is None


def test_document_inputs_carry_title_or_none_and_queries_the_search_prefix(make_models):
    models = make_models()
    models.embed_texts(
        ["pressure rose to 12.4 bar", "no title here"],
        EmbedKind.DOCUMENT,
        ["Test Report 37 › 3.2 Chamber Pressure", None],
    )
    models.embed_texts(["TP37 chamber pressure"], EmbedKind.QUERY)
    assert models.embedder.inputs == [
        "title: Test Report 37 › 3.2 Chamber Pressure | text: pressure rose to 12.4 bar",
        "title: none | text: no title here",
        "task: search result | query: TP37 chamber pressure",
    ]


def test_vectors_are_768_d_unit_length(make_models):
    vectors = make_models(vector=[0.3] * 768).embed_texts(["a b"], EmbedKind.QUERY)
    assert len(vectors[0]) == 768
    assert math.isclose(math.fsum(x * x for x in vectors[0]), 1.0, rel_tol=1e-9)


def test_text_above_8000_tokens_is_refused_not_truncated(make_models):
    models = make_models()
    with pytest.raises(InputTooLong, match="8001 tokens > 8000"):
        models.embed_texts(["w " * 8001], EmbedKind.DOCUMENT)
    assert models.embedder.inputs == []


def test_nan_vector_is_an_error(make_models):
    with pytest.raises(RuntimeError, match="finite"):
        make_models(vector=[float("nan")] * 768).embed_texts(["a"], EmbedKind.QUERY)


def test_wrong_dimension_is_an_error(make_models):
    with pytest.raises(RuntimeError, match="512 dimensions"):
        make_models(vector=[0.1] * 512).embed_texts(["a"], EmbedKind.QUERY)


def test_rank_scores_orders_descending_and_reports_margin_between_rank_1_and_5():
    result = rank_scores([0.1, 0.9, 0.5, 0.3, 0.7, 0.2])
    assert result.order == [1, 4, 2, 3, 5, 0]
    assert result.margin_1_5 == pytest.approx(0.9 - 0.2)


def test_rank_scores_has_no_margin_below_five_passages():
    assert rank_scores([0.2, 0.4]).margin_1_5 is None


def test_cuda_out_of_memory_halves_the_batch_and_retries(make_models):
    import torch

    models = make_models()
    real_encode = models.embedder.encode
    sizes = []

    def encode(inputs, batch_size, **kwargs):
        sizes.append(batch_size)
        if batch_size > 4:
            raise torch.cuda.OutOfMemoryError("CUDA out of memory")
        return real_encode(inputs, **kwargs)

    models.embedder.encode = encode
    assert len(models.embed_texts(["a"] * 3, EmbedKind.QUERY)) == 3
    assert sizes == [16, 8, 4]
