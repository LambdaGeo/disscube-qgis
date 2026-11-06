import pytest

from conftest import ROOT, needs_disscube
from disscube_qgis.core import checks, meshes, tomlio

EXAMPLES = sorted((ROOT / "examples").glob("*.toml"))


def test_there_are_examples():
    assert EXAMPLES


@pytest.mark.parametrize("path", EXAMPLES, ids=lambda p: p.name)
def test_example_reads_checks_and_round_trips(path):
    p = tomlio.load(path)
    assert checks.errors(p) == []
    assert tomlio.parse(tomlio.dumps(p)) == tomlio.parse(path.read_text(encoding="utf-8"))


def test_brasil_2200m_grid():
    g = tomlio.load(ROOT / "examples" / "brasil_2200m_seats.toml").grid
    assert (g.cols, g.rows) == (2491, 2421)
    assert meshes.check(g, "bdc-sm").ok


@needs_disscube
@pytest.mark.parametrize("path", EXAMPLES, ids=lambda p: p.name)
def test_example_passes_disscube(path):
    from disscube.pipeline import plan

    plan(path)
