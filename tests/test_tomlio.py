import pytest

from conftest import CASES, FIXTURES, needs_disscube
from disscube_qgis.core import build, meshes, tomlio


@pytest.mark.parametrize("case", CASES + [FIXTURES / "olw_derivations.template.toml"], ids=lambda c: c.name)
def test_round_trip_keeps_the_content(case):
    """Reading a case and writing it again gives the same TOML data (comments aside)."""
    text = case.read_text(encoding="utf-8")
    p = tomlio.loads(text)
    out = tomlio.dumps(p)
    assert tomlio.parse(out) == tomlio.parse(text)
    assert p.had_comments
    # and the written text is stable
    assert tomlio.dumps(tomlio.loads(out)) == out


def test_writer_escapes_and_nests():
    g = meshes.fit_albers("t", (4.5e6, 1.02e7, 4.6e6, 1.03e7), 5280.0)
    p = build.new_pipeline(g, 'Pará — "test"')
    p.sources.append(tomlio.Item({"id": "s", "type": "prodes", "years": [2024], "codes": {"forest": 1, "water": 4}}))
    p.derives.append(tomlio.Item({"target": "c", "source": "s", "operator": "majority",
                                  "params": {"subcells": 64, "groups": {"1": [1, 2], "a b": [3]}}}))
    p.export = {"output": "out.tif", "variables": ["c"]}
    text = tomlio.dumps(p)
    d = tomlio.parse(text)
    assert d["name"] == 'Pará — "test"'
    assert d["source"][0]["codes"] == {"forest": 1, "water": 4}
    assert d["derive"][0]["params"] == {"subcells": 64, "groups": {"1": [1, 2], "a b": [3]}}
    assert d["export"]["variables"] == ["c"]
    assert d["grid"]["crs"] == "EPSG:10857" and d["grid"]["resolution"] == 5280


def test_top_level_export_string_stays_at_the_top():
    p = tomlio.Pipeline(name="x")
    p.export = "data/x.tif"
    p.derives.append(tomlio.Item({"target": "a", "source": "b", "operator": "mean"}))
    assert tomlio.parse(tomlio.dumps(p))["export"] == "data/x.tif"


def test_floats():
    assert tomlio.value(1e-4) == "0.0001"
    assert tomlio.value(1e-7) == "1.0e-07"
    assert tomlio.value(5280.0) == "5280.0"


def test_rejects_other_crs():
    with pytest.raises(ValueError, match="not BDC Albers"):
        tomlio.loads('schema = 1\n[grid]\nname = "g"\ncrs = "EPSG:31983"\nresolution = 30\nbbox = [0, 0, 30, 30]\n')


@needs_disscube
@pytest.mark.parametrize("case", CASES, ids=lambda c: c.name)
def test_written_files_pass_disscube_validate(case, tmp_path):
    from disscube.pipeline import plan

    out = tmp_path / case.name
    tomlio.dump(tomlio.load(case), out)
    plan(out)   # raises on an invalid file
