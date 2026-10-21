import numpy as np
import pytest

from backend.llm_engine.local_models import EMBEDDING_DIM, LocalModels


class FakeEmbedder:
    def __init__(self, vector=None):
        self.inputs = []
        self.vector = vector

    def encode(self, inputs, **_):
        self.inputs.extend(inputs)
        if self.vector is not None:
            return np.array([self.vector for _ in inputs], dtype=np.float32)
        out = np.zeros((len(inputs), EMBEDDING_DIM), dtype=np.float32)
        out[:, 0] = 0.6
        out[:, 1] = 0.8
        return out


class FakeReranker:
    def predict(self, pairs, **_):
        return np.array([float(len(passage)) for _, passage in pairs], dtype=np.float32)


def word_count(texts):
    return [len(t.split()) for t in texts]


def fake_models(vector=None) -> LocalModels:
    return LocalModels(
        FakeEmbedder(vector), FakeReranker(), device="cpu", dtype="float32", token_counter=word_count
    )


@pytest.fixture
def make_models():
    return fake_models
