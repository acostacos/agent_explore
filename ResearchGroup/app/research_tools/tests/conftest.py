import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


@pytest.fixture(autouse=True)
def no_throttle(monkeypatch):
    import arxiv
    import brave

    monkeypatch.setattr(arxiv, "MIN_INTERVAL_SECONDS", 0)
    monkeypatch.setattr(brave, "MIN_INTERVAL_SECONDS", 0)
