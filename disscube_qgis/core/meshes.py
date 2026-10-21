"""Meshes the grids of a DisSCube pipeline can be aligned to, and the arithmetic to fit and check a grid.

Two families of mesh are in use with DisSCube, both in BDC Albers (EPSG:10857):

``albers0``
    Multiples of the resolution from the origin of the projection (x = 0, y = 0). This is what DisSCube does
    with a ``[grid]`` given in longitude/latitude and no ``crs`` (``disscube.utils.register_local_grid``):
    the four corners of the rectangle are projected and the bounds are rounded out to the resolution.
    Two such grids align when one resolution divides the other.

``bdc-sm``, ``bdc-md``, ``bdc-lg``
    The tiles of the Brazil Data Cube Grid V2 (small, medium and large: 105.6, 211.2 and 422.4 km). They
    follow a closed formula, checked against every tile of the shapefiles bundled with DisSCube::

        xmin(h) = 2 624 000 + h · L        ymax(v) = 11 953 600 − v · L

    A grid nests in the tiles when its resolution divides L and its corner lies a whole number of cells from
    the tile origin; then every cell lies inside exactly one tile. 5 280 m (20 × 20 cells per small tile) and
    10 560 m (10 × 10) are the resolutions of the open-lucc-workflow.

The two families do not coincide: the tile origin is 89 600 m east and 20 800 m north of a multiple of
105 600 m from zero, so a grid on ``albers0`` never nests in the BDC tiles at 5 280 m, and 5 000 m or 1 000 m
never divide a tile.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from . import albers

TILE_X0 = 2_624_000.0
TILE_YMAX = 11_953_600.0
TILE_LEVELS: dict[str, float] = {"SM": 105_600.0, "MD": 211_200.0, "LG": 422_400.0}

_EPS = 1e-6


@dataclass(frozen=True)
class Mesh:
    key: str
    label: str
    tile_level: str | None   # SM, MD, LG; None for albers0

    @property
    def tile_size(self) -> float | None:
        return TILE_LEVELS[self.tile_level] if self.tile_level else None

    @property
    def origin(self) -> tuple[float, float]:
        """(x of the western edge, y of the northern edge) the cells are counted from."""
        return (TILE_X0, TILE_YMAX) if self.tile_level else (0.0, 0.0)


MESHES: dict[str, Mesh] = {
    "bdc-sm": Mesh("bdc-sm", "BDC tiles SM (105.6 km)", "SM"),
    "bdc-md": Mesh("bdc-md", "BDC tiles MD (211.2 km)", "MD"),
    "bdc-lg": Mesh("bdc-lg", "BDC tiles LG (422.4 km)", "LG"),
    "albers0": Mesh("albers0", "Albers from the origin (DisSCube default)", None),
}
DEFAULT_MESH = "bdc-sm"

#: Resolutions offered for the albers0 mesh (any positive value works there).
ALBERS0_RESOLUTIONS = [30.0, 100.0, 250.0, 300.0, 500.0, 1000.0, 2500.0, 5000.0, 10000.0]


def mesh(key: str) -> Mesh:
    try:
        return MESHES[key]
    except KeyError:
        raise ValueError(f"unknown mesh {key!r}; the meshes are {', '.join(MESHES)}") from None


# ── tiles ───────────────────────────────────────────────────────────────────

def parse_tile_id(tile_id: str) -> tuple[int, int]:
    tile_id = tile_id.strip()
    if len(tile_id) != 6 or not tile_id.isdigit():
        raise ValueError(f"a BDC tile id has six digits, hhhvvv (e.g. 019015); got {tile_id!r}")
    return int(tile_id[:3]), int(tile_id[3:])


def tile_bounds(level: str, tile_id: str) -> tuple[float, float, float, float]:
    """(xmin, ymin, xmax, ymax) of a BDC tile in BDC Albers."""
    size = TILE_LEVELS[level.upper()]
    h, v = parse_tile_id(tile_id)
    xmin = TILE_X0 + h * size
    ymax = TILE_YMAX - v * size
    return xmin, ymax - size, xmin + size, ymax


@lru_cache(maxsize=1)
def _tile_table() -> dict:
    path = Path(__file__).resolve().parent / "data" / "bdc_tiles.json"
    return json.loads(path.read_text(encoding="utf-8"))


def existing_tiles(level: str) -> list[str]:
    """Ids of the tiles of BDC Grid V2 at this level (871 SM, 242 MD, 75 LG)."""
    return list(_tile_table()["levels"][level.upper()]["tiles"])


def tiles_covering(level: str, bbox: tuple[float, float, float, float], only_existing: bool = True) -> list[str]:
    """Ids of the tiles that intersect an Albers bbox (with area, not just touching)."""
    size = TILE_LEVELS[level.upper()]
    xmin, ymin, xmax, ymax = bbox
    h0 = math.floor((xmin - TILE_X0) / size + _EPS)
    h1 = math.ceil((xmax - TILE_X0) / size - _EPS) - 1
    v0 = math.floor((TILE_YMAX - ymax) / size + _EPS)
    v1 = math.ceil((TILE_YMAX - ymin) / size - _EPS) - 1
    ids = [f"{h:03d}{v:03d}" for v in range(max(v0, 0), v1 + 1) for h in range(max(h0, 0), h1 + 1)]
    if only_existing:
        have = set(existing_tiles(level))
        ids = [t for t in ids if t in have]
    return ids


def tiles_bbox(level: str, tile_ids: list[str]) -> tuple[float, float, float, float]:
    """Albers bbox of a set of tiles."""
    if not tile_ids:
        raise ValueError("no tiles given")
    bs = [tile_bounds(level, t) for t in tile_ids]
    return min(b[0] for b in bs), min(b[1] for b in bs), max(b[2] for b in bs), max(b[3] for b in bs)


def brazil_bbox(level: str = "SM") -> tuple[float, float, float, float]:
    """Albers bbox of all the tiles of a level: the extent of the BDC grid over Brazil."""
    return tiles_bbox(level, existing_tiles(level))


# ── resolutions ─────────────────────────────────────────────────────────────

def divisors(length: float, minimum: float = 30.0) -> list[float]:
    """Whole-metre resolutions that divide ``length`` exactly, from ``minimum`` up."""
    n = int(round(length))
    small = [d for d in range(1, int(math.isqrt(n)) + 1) if n % d == 0]
    allds = sorted(set(small + [n // d for d in small]))
    return [float(d) for d in allds if d >= minimum]


def resolutions(mesh_key: str, minimum: float = 30.0) -> list[float]:
    """Resolutions offered for a mesh: the divisors of the tile, or common values for albers0."""
    m = mesh(mesh_key)
    if m.tile_size is None:
        return [r for r in ALBERS0_RESOLUTIONS if r >= minimum]
    return divisors(m.tile_size, minimum)


def _whole(value: float) -> bool:
    return abs(value - round(value)) < _EPS


def nests(mesh_key: str, resolution: float) -> bool:
    """True if cells of this resolution fit a whole number of times in a tile of the mesh."""
    m = mesh(mesh_key)
    if resolution <= 0:
        return False
    return True if m.tile_size is None else _whole(m.tile_size / resolution)


# ── grids ───────────────────────────────────────────────────────────────────

def res_label(resolution: float) -> str:
    """How DisSCube names a resolution in a grid id (``disscube.utils.register_local_grid``)."""
    if resolution >= 1000 and math.isclose(resolution % 1000, 0, abs_tol=1e-5):
        return f"{int(resolution // 1000)}km"
    return f"{int(resolution)}m"


@dataclass
class Grid:
    """A grid as it is written in a pipeline file, plus what the plugin knows about it.

    ``form`` says how the [grid] block is written:

    * ``"geo"``: ``bbox`` in longitude/latitude and no ``crs``; DisSCube projects and snaps it (albers0 mesh).
      ``bbox_albers`` holds the result DisSCube will compute, and ``grid_id`` the id it registers.
    * ``"albers"``: ``crs`` and ``bbox`` in BDC Albers, taken as given.
    """

    name: str
    resolution: float
    form: str                                    # "geo" | "albers"
    bbox_albers: tuple[float, float, float, float]
    bbox_geo: tuple[float, float, float, float] | None = None   # what is written when form == "geo"
    crs: str | None = None                       # what is written when form == "albers"
    snap: bool = True
    mesh: str | None = None                      # the mesh it was fitted to, when known
    provenance: list[str] = field(default_factory=list)

    @property
    def cols(self) -> int:
        return round((self.bbox_albers[2] - self.bbox_albers[0]) / self.resolution)

    @property
    def rows(self) -> int:
        return round((self.bbox_albers[3] - self.bbox_albers[1]) / self.resolution)

    @property
    def cells(self) -> int:
        return self.rows * self.cols

    @property
    def grid_id(self) -> str:
        """The id DisSCube registers the grid under (and that ``disscube export`` looks for)."""
        return f"{self.name}/{res_label(self.resolution)}" if self.form == "geo" else self.name

    @property
    def area_km2(self) -> float:
        return self.cells * (self.resolution / 1000.0) ** 2

    def geo_extent(self) -> tuple[float, float, float, float]:
        return albers.bounds_to_geo(*self.bbox_albers)

    def toml_table(self) -> dict:
        """The [grid] table to write."""
        if self.form == "geo":
            assert self.bbox_geo is not None
            t: dict = {"name": self.name, "bbox": [float(v) for v in self.bbox_geo], "resolution": _num(self.resolution)}
            if not self.snap:
                t["snap"] = False
            return t
        return {"name": self.name, "crs": self.crs or albers.CRS, "resolution": _num(self.resolution),
                "bbox": [float(v) for v in self.bbox_albers]}


def _num(v: float) -> int | float:
    return int(v) if _whole(v) else float(v)


def fit_geo(name: str, lonlat: tuple[float, float, float, float], resolution: float, snap: bool = True) -> Grid:
    """The grid DisSCube builds from a lon/lat [grid] with no ``crs`` (albers0 mesh).

    Same arithmetic as ``disscube.utils.register_local_grid``: the four corners are projected, and the bounds are
    rounded out to multiples of the resolution from the origin.
    """
    if resolution <= 0:
        raise ValueError("the resolution must be positive")
    lon0, lat0, lon1, lat1 = lonlat
    if lon0 >= lon1 or lat0 >= lat1:
        raise ValueError("the bbox must be [lon_min, lat_min, lon_max, lat_max] with min < max")
    corners = [(lon0, lat0), (lon0, lat1), (lon1, lat1), (lon1, lat0)]
    xs, ys = zip(*(albers.forward(lo, la) for lo, la in corners))
    minx, miny, maxx, maxy = min(xs), min(ys), max(xs), max(ys)
    if snap:
        minx = math.floor(minx / resolution) * resolution
        miny = math.floor(miny / resolution) * resolution
        maxx = math.ceil(maxx / resolution) * resolution
        maxy = math.ceil(maxy / resolution) * resolution
    return Grid(name=name, resolution=resolution, form="geo", bbox_albers=(minx, miny, maxx, maxy),
                bbox_geo=tuple(lonlat), snap=snap, mesh="albers0" if snap else None)


def fit_albers(name: str, bbox: tuple[float, float, float, float], resolution: float,
               mesh_key: str = DEFAULT_MESH, to_tiles: bool = False) -> Grid:
    """Round an Albers bbox out to the cells of a mesh (or to whole tiles, with ``to_tiles``)."""
    m = mesh(mesh_key)
    if not nests(mesh_key, resolution):
        raise ValueError(f"{resolution:g} m does not divide the {m.tile_size:g} m tiles of {m.key}; "
                         f"try one of {', '.join(f'{r:g}' for r in resolutions(mesh_key)[:12])}, …")
    step = m.tile_size if (to_tiles and m.tile_size) else resolution
    ox, oy = m.origin
    xmin, ymin, xmax, ymax = bbox
    if xmin >= xmax or ymin >= ymax:
        raise ValueError("empty bbox")
    gx0 = ox + math.floor((xmin - ox) / step + _EPS) * step
    gx1 = ox + math.ceil((xmax - ox) / step - _EPS) * step
    gy1 = oy - math.floor((oy - ymax) / step + _EPS) * step
    gy0 = oy - math.ceil((oy - ymin) / step - _EPS) * step
    return Grid(name=name, resolution=resolution, form="albers", bbox_albers=(gx0, gy0, gx1, gy1),
                crs=albers.CRS, mesh=m.key)


def fit_lonlat(name: str, lonlat: tuple[float, float, float, float], resolution: float,
               mesh_key: str = DEFAULT_MESH, to_tiles: bool = False) -> Grid:
    """A lon/lat rectangle on a mesh: albers0 gives the DisSCube lon/lat form, a BDC mesh an explicit Albers grid."""
    if mesh_key == "albers0":
        return fit_geo(name, lonlat, resolution)
    return fit_albers(name, albers.bounds_to_albers(*lonlat), resolution, mesh_key, to_tiles)


def from_table(table: dict) -> Grid:
    """A Grid from the [grid] table of a pipeline file."""
    for k in ("name", "bbox", "resolution"):
        if k not in table:
            raise ValueError(f"[grid] has no {k!r}")
    bbox = tuple(float(v) for v in table["bbox"])
    if len(bbox) != 4:
        raise ValueError("[grid] bbox must have four numbers")
    res = float(table["resolution"])
    crs = table.get("crs")
    if crs is None:
        g = fit_geo(str(table["name"]), bbox, res, snap=bool(table.get("snap", True)))
        return g
    if not albers.is_bdc_albers(crs):
        raise ValueError(f"[grid] crs {crs!r} is not BDC Albers; the plugin only handles BDC Albers grids")
    g = Grid(name=str(table["name"]), resolution=res, form="albers", bbox_albers=bbox, crs=crs)
    found = [k for k in MESHES if check(g, k).ok]
    g.mesh = next((k for k in ("bdc-sm", "bdc-md", "bdc-lg", "albers0") if k in found), None)
    return g


def from_raster(name: str, xmin: float, ymax: float, res_x: float, res_y: float, cols: int, rows: int) -> Grid:
    """A Grid with the cells of a north-up raster in BDC Albers (``res_y`` as a positive size)."""
    if abs(abs(res_x) - abs(res_y)) > 1e-6:
        raise ValueError(f"the raster cells are not square ({res_x} × {res_y})")
    r = abs(res_x)
    g = Grid(name=name, resolution=r, form="albers", crs=albers.CRS,
             bbox_albers=(xmin, ymax - rows * abs(res_y), xmin + cols * r, ymax))
    found = [k for k in MESHES if check(g, k).ok]
    g.mesh = next((k for k in ("bdc-sm", "bdc-md", "bdc-lg", "albers0") if k in found), None)
    return g


# ── checking ────────────────────────────────────────────────────────────────

@dataclass
class Check:
    mesh: str
    ok: bool
    lines: list[str]


def check(grid: Grid, mesh_key: str) -> Check:
    """Does the grid nest in the mesh? Says why not, in cells."""
    m = mesh(mesh_key)
    lines: list[str] = []
    r = grid.resolution
    xmin, ymin, xmax, ymax = grid.bbox_albers
    ok = True
    if m.tile_size is not None and not _whole(m.tile_size / r):
        ok = False
        lines.append(f"{r:g} m does not divide the {m.tile_size:g} m tiles ({m.tile_size / r:.4g} cells per tile side)")
    ox, oy = m.origin
    dx = (xmin - ox) / r
    dy = (oy - ymax) / r
    if not _whole(dx):
        ok = False
        lines.append(f"western edge is {dx % 1:.3f} of a cell off the mesh ({xmin - ox:,.1f} m from x = {ox:,.0f})")
    if not _whole(dy):
        ok = False
        lines.append(f"northern edge is {dy % 1:.3f} of a cell off the mesh ({oy - ymax:,.1f} m from y = {oy:,.0f})")
    if not _whole((xmax - xmin) / r) or not _whole((ymax - ymin) / r):
        ok = False
        lines.append("the bbox is not a whole number of cells wide or tall")
    if ok:
        if m.tile_size is not None:
            per = int(round(m.tile_size / r))
            lines.append(f"nests in the {m.tile_level} tiles: {per} × {per} cells per tile")
        else:
            lines.append("on the albers0 mesh (multiples of the resolution from the origin)")
    return Check(m.key, ok, lines)


# ── cost estimate ───────────────────────────────────────────────────────────

#: Native pixel size (m) of the common sources, for the estimate of how much each one reads.
SOURCE_PIXEL = {"MapBiomas (30 m)": 30.0, "PRODES (30 m)": 30.0, "Landsat BDC (30 m)": 30.0, "MODIS BDC (231.66 m)": 231.656}
BLOCK_PIXELS = 50_000_000   # DisSCube default (DISSCUBE_BLOCK_PIXELS)


def source_pixels(grid: Grid) -> dict[str, tuple[int, int]]:
    """For each common source: (pixels read over the grid, blocks of BLOCK_PIXELS). An estimate."""
    w = grid.bbox_albers[2] - grid.bbox_albers[0]
    h = grid.bbox_albers[3] - grid.bbox_albers[1]
    out = {}
    for name, px in SOURCE_PIXEL.items():
        n = int(math.ceil(w / px) * math.ceil(h / px))
        out[name] = (n, max(1, math.ceil(n / BLOCK_PIXELS)))
    return out
