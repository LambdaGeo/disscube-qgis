"""Start a pipeline from a grid, with the comments that say where the grid came from."""

from __future__ import annotations

from . import __version__, meshes
from .tomlio import Pipeline


def describe(grid: meshes.Grid, area: str) -> list[str]:
    """Comment lines for the [grid] block: tool, mesh, area, tiles."""
    lines = [f"Grid made with the DisSCube plugin for QGIS {__version__}."]
    if grid.form == "geo":
        lines.append("Mesh albers0: DisSCube projects the lon/lat bbox to BDC Albers and rounds it out to the resolution.")
    elif grid.mesh:
        m = meshes.mesh(grid.mesh)
        if m.tile_size:
            per = int(round(m.tile_size / grid.resolution))
            t = meshes.tiles_covering(m.tile_level, grid.bbox_albers)
            span = ""
            if t:
                hs, vs = sorted({x[:3] for x in t}), sorted({x[3:] for x in t})
                span = f"; tiles h {hs[0]}–{hs[-1]}, v {vs[0]}–{vs[-1]}"
            lines.append(f"Mesh {m.key}: BDC Grid V2 {m.tile_level} tiles of {m.tile_size / 1000:g} km, "
                         f"{per} x {per} cells per tile{span}.")
        else:
            lines.append("Mesh albers0: multiples of the resolution from the origin of BDC Albers.")
    if area:
        lines.append(f"Area: {area}")
    return lines


def new_pipeline(grid: meshes.Grid, name: str | None, area: str = "", commands: list[str] | None = None) -> Pipeline:
    grid.provenance = describe(grid, area)
    header = [name or grid.name, ""] if (name or grid.name) else []
    header += ["    disscube validate <this file>",
               f"    disscube run <this file> --workspace data/{grid.name} --output data/{grid.name}.tif"]
    if commands:
        header = [name or grid.name, ""] + [f"    {c}" for c in commands]
    return Pipeline(name=name, grid=grid, header=header)
