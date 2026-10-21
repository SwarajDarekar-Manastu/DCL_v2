import pytest

from backend.llm_engine.local_models import EMBEDDING_DIM, LocalModels


class Vectors(list):
    """What sentence-transformers returns with convert_to_numpy=True, as far as LocalModels uses it."""

    def tolist(self):
        return [list(row) for row in self]


class FakeEmbedder:
    def __init__(self, vector=None):
        self.inputs = []
        self.vector = vector

    def encode(self, inputs, **_):
        self.inputs.extend(inputs)
        if self.vector is not None:
            return Vectors([list(self.vector) for _ in inputs])
        return Vectors([[0.6, 0.8] + [0.0] * (EMBEDDING_DIM - 2) for _ in inputs])


class FakeReranker:
    def predict(self, pairs, **_):
        return [float(len(passage)) for _, passage in pairs]


def word_count(texts):
    return [len(t.split()) for t in texts]


def fake_models(vector=None) -> LocalModels:
    return LocalModels(
        FakeEmbedder(vector), FakeReranker(), device="cpu", dtype="float32", token_counter=word_count
    )


@pytest.fixture
def make_models():
    return fake_models
