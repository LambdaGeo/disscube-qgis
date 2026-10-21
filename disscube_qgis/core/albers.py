"""BDC Albers equal-area projection (SIRGAS 2000 / Brazil Albers, EPSG:10857), in pure Python.

The grid arithmetic of the plugin needs to go from longitude/latitude to the BDC Albers coordinates and back.
QGIS can do that, but the core is kept free of QGIS and pyproj so that it runs (and is tested) anywhere, and so
that the plugin, the Processing algorithms and the tests compute the same numbers.

Formulas: J. P. Snyder, *Map Projections — A Working Manual*, USGS Professional Paper 1395 (1987), pp. 101–102,
ellipsoidal form. Parameters: GRS80 ellipsoid, latitude of origin −12°, central meridian −54°, standard parallels
−2° and −22°, false easting 5 000 000 m, false northing 10 000 000 m. ``tests/test_albers.py`` checks the result
against pyproj to a millimetre.
"""

from __future__ import annotations

import math

A = 6378137.0
F = 1 / 298.257222101
E2 = F * (2 - F)
E = math.sqrt(E2)

LAT0 = math.radians(-12.0)
LON0 = math.radians(-54.0)
LAT1 = math.radians(-2.0)
LAT2 = math.radians(-22.0)
X0 = 5_000_000.0
Y0 = 10_000_000.0

#: The CRS the plugin writes in the [grid] block (same coordinates as ``disscube.models.grid.BDC_CRS``).
CRS = "EPSG:10857"
#: The PROJ string DisSCube uses for BDC Albers (``disscube.models.grid.BDC_CRS``).
PROJ = (
    "+proj=aea +lat_0=-12 +lon_0=-54 +lat_1=-2 +lat_2=-22"
    " +x_0=5000000 +y_0=10000000 +ellps=GRS80 +units=m +no_defs"
)


def _q(phi: float) -> float:
    s = math.sin(phi)
    return (1 - E2) * (s / (1 - E2 * s * s) - (1 / (2 * E)) * math.log((1 - E * s) / (1 + E * s)))


def _m(phi: float) -> float:
    s = math.sin(phi)
    return math.cos(phi) / math.sqrt(1 - E2 * s * s)


_M1, _M2 = _m(LAT1), _m(LAT2)
_Q0, _Q1, _Q2 = _q(LAT0), _q(LAT1), _q(LAT2)
N = (_M1 * _M1 - _M2 * _M2) / (_Q2 - _Q1)
C = _M1 * _M1 + N * _Q1
RHO0 = A * math.sqrt(C - N * _Q0) / N


def forward(lon: float, lat: float) -> tuple[float, float]:
    """Longitude and latitude (degrees, SIRGAS 2000 / WGS84) to BDC Albers x, y (metres)."""
    rho = A * math.sqrt(C - N * _q(math.radians(lat))) / N
    theta = N * (math.radians(lon) - LON0)
    return X0 + rho * math.sin(theta), Y0 + RHO0 - rho * math.cos(theta)


def inverse(x: float, y: float) -> tuple[float, float]:
    """BDC Albers x, y (metres) to longitude and latitude (degrees)."""
    dx, dy = x - X0, RHO0 - (y - Y0)
    sign = 1.0 if N > 0 else -1.0
    rho = sign * math.hypot(dx, dy)
    theta = math.atan2(sign * dx, sign * dy)
    q = (C - (rho * N / A) ** 2) / N
    phi = math.asin(max(-1.0, min(1.0, q / 2)))
    for _ in range(50):
        s = math.sin(phi)
        d = ((1 - E2 * s * s) ** 2 / (2 * math.cos(phi))) * (
            q / (1 - E2) - s / (1 - E2 * s * s) + (1 / (2 * E)) * math.log((1 - E * s) / (1 + E * s))
        )
        phi += d
        if abs(d) < 1e-14:
            break
    return math.degrees(LON0 + theta / N), math.degrees(phi)


def bounds_to_albers(lon_min: float, lat_min: float, lon_max: float, lat_max: float,
                     densify: int = 21) -> tuple[float, float, float, float]:
    """Albers bounds of a lon/lat rectangle, following its edges (``densify`` points per edge)."""
    xs: list[float] = []
    ys: list[float] = []
    for i in range(densify):
        t = i / (densify - 1)
        lon = lon_min + t * (lon_max - lon_min)
        lat = lat_min + t * (lat_max - lat_min)
        for p in ((lon, lat_min), (lon, lat_max), (lon_min, lat), (lon_max, lat)):
            x, y = forward(*p)
            xs.append(x)
            ys.append(y)
    return min(xs), min(ys), max(xs), max(ys)


def bounds_to_geo(xmin: float, ymin: float, xmax: float, ymax: float,
                  densify: int = 21) -> tuple[float, float, float, float]:
    """Lon/lat bounds of an Albers rectangle, following its edges."""
    lons: list[float] = []
    lats: list[float] = []
    for i in range(densify):
        t = i / (densify - 1)
        x = xmin + t * (xmax - xmin)
        y = ymin + t * (ymax - ymin)
        for p in ((x, ymin), (x, ymax), (xmin, y), (xmax, y)):
            lon, lat = inverse(*p)
            lons.append(lon)
            lats.append(lat)
    return min(lons), min(lats), max(lons), max(lats)


def is_bdc_albers(crs: str | None) -> bool:
    """True for the ways a pipeline file names BDC Albers (``None`` means the DisSCube default, BDC Albers)."""
    if crs is None:
        return True
    norm = " ".join(crs.split()).lower()
    if norm in {"epsg:10857"}:
        return True
    want = set(PROJ.lower().split())
    have = set(norm.split())
    return want - {"+no_defs"} <= have
