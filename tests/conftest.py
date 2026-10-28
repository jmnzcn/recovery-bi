from pathlib import Path

import pytest

from recovery_bi import data

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="session")
def star() -> data.Star:
    return data.read(ROOT / "data")


@pytest.fixture(scope="session")
def project() -> Path:
    return ROOT / "powerbi"
