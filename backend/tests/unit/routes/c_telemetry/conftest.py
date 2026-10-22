"""Route C tests reuse the sync tests' disposable PostgreSQL and MinIO fixtures, plus a synthetic
LJStreamM file in the crawl's layout (date, time, blank lines, tab-separated header, 1 kHz data)."""

import numpy as np
import pytest

from backend.tests.unit.sync.conftest import engine, minio, session  # noqa: F401

CHANNELS = ["v0", "v1", "y0", "y1"]


def labjack_bytes(
    rows: int = 2500, gap_at: int | None = 1200, newline: str = "\r\n"
) -> tuple[bytes, np.ndarray]:
    """An LJStreamM file and its data matrix (time first). ``gap_at`` drops one sample to make one gap."""
    if gap_at is not None and gap_at >= rows:
        gap_at = rows // 2
    t = np.arange(rows + (1 if gap_at is not None else 0)) * 0.001
    if gap_at is not None:
        t = np.delete(t, gap_at)
    rng = np.random.default_rng(7)
    data = np.column_stack(
        [
            t,
            0.8 + 0.01 * rng.standard_normal(rows),
            2.5 + 0.05 * np.sin(t * 40),
            12.0 + rng.standard_normal(rows),
            np.linspace(-1.0, 5.0, rows),
        ]
    )
    header = ["29-12-2025", "14:18:41", "", "", "Time\t" + "\t".join(CHANNELS)]
    body = ["\t".join(f"{v:.6f}" for v in row) for row in data]
    return (newline.join(header + body) + newline).encode(), data


@pytest.fixture()
def labjack():
    return labjack_bytes()
