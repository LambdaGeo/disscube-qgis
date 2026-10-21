import pytest

from conftest import CASES, needs_disscube
from disscube_qgis.core import meshes, tomlio

# The [grid] of the open-lucc-workflow, as scripts/render_pipeline.py of that repository writes it.
OLW_BBOX = (2465600.0, 7360000.0, 7956800.0, 12112000.0)


def olw_grid(res):
    import math
    x0, y0, x1, y1 = OLW_BBOX
    return meshes.Grid("br", res, "albers", (x0, y0, x0 + math.ceil((x1 - x0) / res) * res,
                                              y0 + math.ceil((y1 - y0) / res) * res), crs="EPSG:10857")


def test_tile_formula():
    assert meshes.tile_bounds("SM", "001014") == (2729600.0, 10369600.0, 2835200.0, 10475200.0)
    assert len(meshes.existing_tiles("SM")) == 871
    assert len(meshes.existing_tiles("MD")) == 242
    assert len(meshes.existing_tiles("LG")) == 75
    assert meshes.brazil_bbox("SM") == (2729600.0, 7518400.0, 7798400.0, 11953600.0)


def test_divisors_of_the_small_tile():
    r = meshes.resolutions("bdc-sm")
    for good in (30, 50, 100, 300, 5280, 10560, 105600):
        assert float(good) in r
    for bad in (250, 500, 1000, 5000):
        assert float(bad) not in r
    assert meshes.nests("bdc-sm", 5280) and not meshes.nests("bdc-sm", 5000)


@pytest.mark.parametrize("res", [5280.0, 10560.0])
def test_open_lucc_workflow_grids_nest_in_the_bdc_tiles(res):
    g = olw_grid(res)
    c = meshes.check(g, "bdc-sm")
    assert c.ok, c.lines
    # and fitting the same bbox to the mesh gives it back
    assert meshes.fit_albers("br", g.bbox_albers, res, "bdc-sm").bbox_albers == g.bbox_albers


def test_br_5km_is_1040_columns_by_900_rows():
    g = olw_grid(5280.0)
    assert (g.cols, g.rows) == (1040, 900)


@pytest.mark.parametrize("case", ["amazonia_legal__prodes.toml", "brasil_5km__mapbiomas.toml"])
def test_grids_counted_from_zero_do_not_nest_in_the_bdc_tiles(case):
    p = tomlio.load([c for c in CASES if c.name == case][0])
    assert not meshes.check(p.grid, "bdc-sm").ok
    assert p.grid.mesh == "albers0"   # multiples of 5 280 m from zero


def test_fit_albers_rounds_out_and_to_tiles():
    g = meshes.fit_albers("x", (4_500_000.0, 10_200_000.0, 4_600_000.0, 10_300_000.0), 5280.0, "bdc-sm")
    assert meshes.check(g, "bdc-sm").ok
    assert g.bbox_albers[0] <= 4_500_000 and g.bbox_albers[2] >= 4_600_000
    t = meshes.fit_albers("x", (4_500_000.0, 10_200_000.0, 4_600_000.0, 10_300_000.0), 5280.0, "bdc-sm", to_tiles=True)
    assert t.bbox_albers == (4419200.0, 10158400.0, 4630400.0, 10369600.0) and (t.cols, t.rows) == (40, 40)


def test_fit_rejects_a_resolution_that_does_not_divide_the_tile():
    with pytest.raises(ValueError, match="does not divide"):
        meshes.fit_albers("x", (4.5e6, 1.02e7, 4.6e6, 1.03e7), 5000.0, "bdc-sm")


def test_from_raster():
    g = meshes.from_raster("br", 2465600.0, 12112000.0, 5280.0, -5280.0, 1040, 900)
    assert g.mesh == "bdc-sm" and g.bbox_albers == olw_grid(5280.0).bbox_albers


@needs_disscube
@pytest.mark.parametrize("case", [c.name for c in CASES])
def test_lonlat_grids_match_disscube(case):
    """For every case with a lon/lat [grid], the plugin computes the grid DisSCube registers."""
    from disscube.utils import register_local_grid

    p = tomlio.load([c for c in CASES if c.name == case][0])
    if p.grid.form != "geo":
        pytest.skip("Albers grid")

    class Cube:
        def register_grid(self, g):
            self.g = g

    cube = Cube()
    t = p.grid.toml_table()
    want = register_local_grid(cube, name=t["name"], bbox_geo=tuple(t["bbox"]), resolution=float(t["resolution"]))
    assert p.grid.grid_id == want.id
    assert p.grid.bbox_albers == pytest.approx(tuple(want.bbox), abs=1e-6)
