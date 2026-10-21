import random

from conftest import needs_pyproj
from disscube_qgis.core import albers


@needs_pyproj
def test_forward_and_inverse_match_pyproj_over_brazil():
    from pyproj import Transformer

    fwd = Transformer.from_crs("EPSG:4326", "EPSG:10857", always_xy=True)
    rng = random.Random(1)
    for _ in range(5000):
        lon, lat = rng.uniform(-75, -32), rng.uniform(-35, 6)
        x, y = albers.forward(lon, lat)
        X, Y = fwd.transform(lon, lat)
        assert abs(x - X) < 1e-3 and abs(y - Y) < 1e-3
        lo, la = albers.inverse(X, Y)
        assert abs(lo - lon) < 1e-9 and abs(la - lat) < 1e-9


@needs_pyproj
def test_proj_string_and_epsg_give_the_same_coordinates():
    from pyproj import Transformer

    a = Transformer.from_crs("EPSG:4326", "EPSG:10857", always_xy=True)
    b = Transformer.from_crs("EPSG:4326", albers.PROJ, always_xy=True)
    for p in [(-50, -5), (-70, 3), (-38, -20)]:
        assert a.transform(*p) == b.transform(*p)


def test_is_bdc_albers():
    assert albers.is_bdc_albers(None)
    assert albers.is_bdc_albers("EPSG:10857")
    assert albers.is_bdc_albers(albers.PROJ)
    assert not albers.is_bdc_albers("EPSG:5880")
