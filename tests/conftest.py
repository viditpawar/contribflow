import json
from pathlib import Path

import pytest

from contribflow.config import load_census, load_limits
from generator.generate import generate

REPO_ROOT = Path(__file__).parent.parent


@pytest.fixture(scope="session")
def sample(tmp_path_factory):
    """Freshly generated sample data and its expected outcomes manifest."""
    out = tmp_path_factory.mktemp("sample")
    generate(42, out)
    manifest = json.loads((out / "expected_outcomes.json").read_text())
    return out, manifest


@pytest.fixture(scope="session")
def census(sample):
    out, _ = sample
    return load_census(out / "census.csv")


@pytest.fixture(scope="session")
def limits():
    return load_limits(REPO_ROOT / "config" / "limits.yaml")
