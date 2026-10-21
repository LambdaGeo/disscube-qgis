"""Checks the plugin runs on a pipeline before saving it, without DisSCube.

They catch the mistakes a form can let through (a misspelt source id, a field a source type does not have, an
operator parameter that does not exist, a PRODES year before 2007). They are not a replacement for
``disscube validate``, which the plugin runs when a DisSCube is configured: the checks here follow the catalog
of the DisSCube version the plugin was built against, and stop at what can be known without reading the data.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from . import catalog, meshes
from .tomlio import Pipeline

WINDOWED = {"bdc", "mapbiomas", "prodes", "classified", "osm", "dem"}


@dataclass
class Problem:
    level: str      # "error" | "warning"
    where: str
    message: str

    def __str__(self) -> str:
        return f"{self.level}: {self.where}: {self.message}"


def _kind_ok(v: Any, kinds: list[str]) -> bool:
    for k in kinds:
        if k == "any":
            return True
        if k == "str" and isinstance(v, str):
            return True
        if k == "bool" and isinstance(v, bool):
            return True
        if k == "int" and isinstance(v, int) and not isinstance(v, bool):
            return True
        if k == "float" and isinstance(v, (int, float)) and not isinstance(v, bool):
            return True
        if k == "table" and isinstance(v, dict):
            return True
        if k.startswith("list[") and isinstance(v, list):
            item = k[5:-1]
            test = {"integer": "int", "number": "float", "string": "str", "boolean": "bool"}.get(item, "any")
            if all(_kind_ok(x, [test]) for x in v):
                return True
    return False


def _fields(where: str, data: dict[str, Any], fields: dict[str, dict], out: list[Problem]) -> None:
    for k, v in data.items():
        if k not in fields:
            out.append(Problem("error", where, f"unknown field {k!r} (fields: {', '.join(sorted(fields))})"))
            continue
        f = fields[k]
        if v is None:
            continue
        if not _kind_ok(v, f["kinds"]):
            out.append(Problem("error", where, f"{k!r} should be {' or '.join(f['kinds'])}, got {v!r}"))
        elif "enum" in f and v not in f["enum"]:
            out.append(Problem("error", where, f"{k!r} must be one of {f['enum']}, got {v!r}"))
        if "min_items" in f and isinstance(v, list) and len(v) < f["min_items"]:
            out.append(Problem("error", where, f"{k!r} needs at least {f['min_items']} items"))
    for k, f in fields.items():
        if f.get("required") and data.get(k) is None:
            out.append(Problem("error", where, f"missing {k!r}"))


def check(p: Pipeline) -> list[Problem]:
    out: list[Problem] = []
    cat = catalog.catalog()

    # top level
    allowed_top = set(catalog.top_fields()) | {"export"}
    for k in p.top:
        if k not in allowed_top:
            out.append(Problem("error", "file", f"unknown top-level key {k!r}"))

    # grid
    if p.grid is not None:
        g = p.grid
        if g.resolution <= 0:
            out.append(Problem("error", "[grid]", "resolution must be positive"))
        if g.cells == 0:
            out.append(Problem("error", "[grid]", "the grid has no cells"))
        if g.form == "albers" and g.mesh is None:
            out.append(Problem("warning", "[grid]", "the grid is on none of the known meshes (albers0, BDC tiles)"))
        if g.cells > 5_000_000:
            out.append(Problem("warning", "[grid]", f"{g.cells:,} cells; check the resolution"))
    if p.derives and p.grid is None:
        out.append(Problem("error", "file", "a file with [[derive]] blocks needs a [grid]"))
    if p.grid is None and not p.top.get("extent") and any(s.get("type") in WINDOWED for s in p.sources):
        out.append(Problem("error", "file", "a file with no [grid] and windowed sources (BDC, MapBiomas, PRODES, "
                                           "OSM, DEM, classified) needs `extent`"))

    # sources
    ids: list[str] = []
    templates: dict[str, list[int] | None] = {}
    vector_like: set[str] = set()
    for i, s in enumerate(p.sources, 1):
        sid = str(s.get("id") or f"#{i}")
        where = f"source {sid}"
        typ = s.get("type")
        if typ not in cat["sources"]:
            out.append(Problem("error", where, f"unknown type {typ!r} (types: {', '.join(catalog.source_types())})"))
            continue
        _fields(where, s.data, catalog.source_fields(typ), out)
        years = s.get("years")
        if years is not None and "{year}" not in sid:
            out.append(Problem("error", where, "'years' requires '{year}' in the id"))
        templates[sid] = years
        concrete = [sid.replace("{year}", str(y)) for y in years] if years else [sid]
        ids.extend(concrete)
        if typ in ("mapbiomas", "prodes"):
            ys = years if years else ([s.get("year")] if s.get("year") is not None else [])
            if not ys:
                out.append(Problem("error", where, "needs 'year' (or 'years' with '{year}')"))
            for y in ys:
                try:
                    y = int(y)
                except (TypeError, ValueError):
                    continue
                if typ == "prodes" and y < cat["prodes"]["first_separable_year"]:
                    out.append(Problem("error", where, f"PRODES separates years from "
                                                       f"{cat['prodes']['first_separable_year']} on; {y} cannot be asked"))
                if typ == "mapbiomas":
                    c, r = s.get("collection", 11), s.get("resolution", 30)
                    ds = [d for d in cat["mapbiomas"]["datasets"] if d["collection"] == c and d["resolution"] == r]
                    if not ds:
                        out.append(Problem("error", where, f"no MapBiomas collection {c} at {r} m"))
                    elif not ds[0]["first_year"] <= y <= ds[0]["last_year"]:
                        out.append(Problem("error", where, f"collection {c} ({r} m) covers "
                                                           f"{ds[0]['first_year']}–{ds[0]['last_year']}; got {y}"))
        if typ == "bdc" and (s.get("asset") is None) == (s.get("normalized_difference") is None):
            out.append(Problem("error", where, "give exactly one of 'asset' or 'normalized_difference'"))
        if typ == "dem" and (s.get("dem") is None) == (s.get("tiles") is None):
            out.append(Problem("error", where, "give exactly one of 'dem' or 'tiles'"))
        if typ == "union":
            for part in s.get("of") or []:
                if part not in ids[: len(ids) - len(concrete)]:
                    out.append(Problem("error", where, f"{part!r} must be a source declared before it"))
            vector_like.update(concrete)
        if typ == "file" and (s.get("format") == "vector" or str(s.get("path", "")).lower().endswith(
                (".shp", ".gpkg", ".geojson", ".json", ".fgb", ".parquet"))):
            vector_like.update(concrete)
    dup = sorted({i for i in ids if ids.count(i) > 1})
    if dup:
        out.append(Problem("error", "sources", f"duplicate source ids: {', '.join(dup)}"))

    # derives
    ops = catalog.operators()
    targets: list[tuple[str, str]] = []
    for i, d in enumerate(p.derives, 1):
        where = f"variable {d.get('target') or f'#{i}'}"
        _fields(where, d.data, catalog.derive_fields(), out)
        op = d.get("operator")
        if op is not None and op not in ops:
            out.append(Problem("error", where, f"unknown operator {op!r}"))
        elif op is not None:
            o = ops[op]
            if o["requires_class_code"] and d.get("class_code") is None:
                out.append(Problem("error", where, f"{op!r} needs class_code"))
            for k in (d.get("params") or {}):
                if k not in o["params"]:
                    allowed = ", ".join(o["params"]) or "none"
                    out.append(Problem("error", where, f"{op!r} has no parameter {k!r} (parameters: {allowed})"))
        src = d.get("source")
        if not isinstance(src, str):
            continue
        if "{year}" in src:
            yrs = d.get("years") or templates.get(src)
            if not yrs:
                out.append(Problem("error", where, f"source {src!r} has '{{year}}' but no years "
                                                   "(give 'years' here or in the matching source block)"))
                continue
            concrete = [src.replace("{year}", str(y)) for y in yrs]
        else:
            if d.get("years"):
                out.append(Problem("error", where, "'years' requires '{year}' in 'source'"))
            concrete = [src]
        for c in concrete:
            if c not in ids and not p.top.get("sources_from_catalog"):
                out.append(Problem("error", where, f"unknown source {c!r} (sources: {', '.join(ids) or 'none'})"))
        targets.extend((str(d.get("target")), c) for c in concrete)
    seen = set()
    for t in targets:
        if t in seen:
            out.append(Problem("warning", f"variable {t[0]}", f"derived twice from {t[1]!r}"))
        seen.add(t)
    return out


def errors(p: Pipeline) -> list[Problem]:
    return [x for x in check(p) if x.level == "error"]


def grid_report(g: meshes.Grid) -> list[str]:
    """Plain lines describing a grid: size, extent, meshes it nests in, tiles, what the sources read."""
    xmin, ymin, xmax, ymax = g.bbox_albers
    lo0, la0, lo1, la1 = g.geo_extent()
    lines = [
        f"grid id   : {g.grid_id}",
        f"cells     : {g.cols} columns x {g.rows} rows = {g.cells:,} ({g.resolution:g} m; {g.area_km2:,.0f} km²)",
        f"Albers    : [{xmin:.1f}, {ymin:.1f}, {xmax:.1f}, {ymax:.1f}]",
        f"lon/lat   : [{lo0:.4f}, {la0:.4f}, {lo1:.4f}, {la1:.4f}]",
    ]
    nests = [k for k in meshes.MESHES if meshes.check(g, k).ok]
    lines.append(f"meshes    : {', '.join(nests) if nests else 'none of the known meshes'}")
    for level in ("SM",):
        try:
            t = meshes.tiles_covering(level, g.bbox_albers)
        except Exception:  # pragma: no cover - tile table missing
            t = []
        if t:
            hs = sorted({x[:3] for x in t})
            vs = sorted({x[3:] for x in t})
            lines.append(f"BDC tiles : {len(t)} {level} (h {hs[0]}–{hs[-1]}, v {vs[0]}–{vs[-1]})")
    for name, (n, blocks) in meshes.source_pixels(g).items():
        lines.append(f"{name:<22}: about {n:,} pixels" + (f", {blocks} blocks" if blocks > 1 else ""))
    return lines
