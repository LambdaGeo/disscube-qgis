import pytest

from conftest import needs_disscube
from disscube_qgis.core import build, checks, meshes, recipes, tomlio

ARGS = {"years": {"years": [2008, 2024]}, "period": {"period": "2020-07-01/2020-09-30"}, "": {}}


def _new():
    g = meshes.fit_lonlat("t", (-55.0, -4.0, -54.5, -3.5), 5280.0, "bdc-sm")
    return build.new_pipeline(g, "test")


@pytest.mark.parametrize("key", list(recipes.RECIPES))
def test_each_recipe_gives_a_valid_file(key):
    p = _new()
    recipes.apply(p, key, **ARGS[recipes.RECIPES[key].needs])
    assert checks.errors(p) == []


def test_recipes_share_a_source_and_merge_years():
    p = _new()
    recipes.apply(p, "mapbiomas-landuse", years=[2024])
    recipes.apply(p, "mapbiomas-l1", years=[2000, 2024])
    assert [s.get("id") for s in p.sources] == ["lulc_{year}"]
    assert p.sources[0].get("years") == [2000, 2024]
    assert [d.get("target") for d in p.derives] == ["landuse", "l1_class"]
    recipes.apply(p, "mapbiomas-landuse", years=[2024])
    assert len(p.derives) == 2


@needs_disscube
@pytest.mark.parametrize("key", list(recipes.RECIPES))
def test_each_recipe_passes_disscube_plan(key, tmp_path):
    from disscube.pipeline import plan

    p = _new()
    recipes.apply(p, key, **ARGS[recipes.RECIPES[key].needs])
    f = tmp_path / "p.toml"
    tomlio.dump(p, f)
    plan(f)
