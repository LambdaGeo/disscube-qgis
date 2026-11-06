"""QGIS side of the grid arithmetic: CRS, extents, and the layers that show a grid and the BDC tiles."""

from __future__ import annotations

import os

from qgis.core import (
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
    QgsFeature,
    QgsField,
    QgsFields,
    QgsGeometry,
    QgsPointXY,
    QgsProject,
    QgsRasterLayer,
    QgsRectangle,
    QgsVectorLayer,
)
from . import compat
from .core import albers, meshes

#: Above this many cells the preview draws the outline and the tiles, not every cell.
MAX_PREVIEW_CELLS = 50_000


def albers_crs() -> QgsCoordinateReferenceSystem:
    """BDC Albers. EPSG:10857 when the PROJ database of this QGIS knows it, else the PROJ string."""
    crs = QgsCoordinateReferenceSystem("EPSG:10857")
    if crs.isValid():
        return crs
    return QgsCoordinateReferenceSystem.fromProj(albers.PROJ)


def wgs84() -> QgsCoordinateReferenceSystem:
    return QgsCoordinateReferenceSystem("EPSG:4326")


def to_lonlat(extent: QgsRectangle, crs: QgsCoordinateReferenceSystem) -> tuple[float, float, float, float]:
    """A rectangle in any CRS as a lon/lat bbox (following its edges)."""
    if crs.isValid() and crs != wgs84():
        tr = QgsCoordinateTransform(crs, wgs84(), QgsProject.instance())
        extent = tr.transformBoundingBox(extent)
    return extent.xMinimum(), extent.yMinimum(), extent.xMaximum(), extent.yMaximum()


def to_albers(extent: QgsRectangle, crs: QgsCoordinateReferenceSystem) -> tuple[float, float, float, float]:
    """A rectangle in any CRS as a BDC Albers bbox (following its edges)."""
    a = albers_crs()
    if crs.isValid() and crs.authid() != a.authid() and crs.toProj() != a.toProj():
        tr = QgsCoordinateTransform(crs, a, QgsProject.instance())
        extent = tr.transformBoundingBox(extent)
    return extent.xMinimum(), extent.yMinimum(), extent.xMaximum(), extent.yMaximum()


def fit_extent(name: str, extent: QgsRectangle, crs: QgsCoordinateReferenceSystem, resolution: float,
               mesh_key: str, to_tiles: bool = False) -> meshes.Grid:
    """The grid on a mesh that covers an extent given in any CRS."""
    if mesh_key == "albers0":
        lonlat = tuple(round(v, 6) for v in to_lonlat(extent, crs))
        return meshes.fit_geo(name, lonlat, resolution)
    return meshes.fit_albers(name, to_albers(extent, crs), resolution, mesh_key, to_tiles)


def grid_from_raster(layer: QgsRasterLayer, name: str) -> meshes.Grid:
    """The grid of a GeoTIFF in BDC Albers (for example the input raster of the open-lucc-workflow)."""
    a = albers_crs()
    lc = layer.crs()
    if not (lc.authid() == a.authid() or lc.toProj() == a.toProj() or albers.is_bdc_albers(lc.toProj())):
        raise ValueError(f"{layer.name()} is in {lc.authid() or lc.description()}, not BDC Albers")
    e = layer.extent()
    return meshes.from_raster(name, e.xMinimum(), e.yMaximum(), layer.rasterUnitsPerPixelX(),
                              layer.rasterUnitsPerPixelY(), layer.width(), layer.height())


def _poly(xmin: float, ymin: float, xmax: float, ymax: float) -> QgsGeometry:
    return QgsGeometry.fromPolygonXY([[QgsPointXY(xmin, ymin), QgsPointXY(xmax, ymin), QgsPointXY(xmax, ymax),
                                       QgsPointXY(xmin, ymax), QgsPointXY(xmin, ymin)]])


def _memory_layer(name: str, fields: QgsFields) -> QgsVectorLayer:
    layer = QgsVectorLayer("Polygon", name, "memory")
    layer.setCrs(albers_crs())
    layer.dataProvider().addAttributes(fields.toList())
    layer.updateFields()
    return layer


def grid_fields(cells: bool) -> QgsFields:
    f = QgsFields()
    if cells:
        f.append(QgsField("row", compat.field_type("Int")))
        f.append(QgsField("col", compat.field_type("Int")))
        f.append(QgsField("cell_id", compat.field_type("String")))
    else:
        for name, typ in (("grid", "String"), ("resolution", "Double"), ("cols", "Int"), ("rows", "Int"),
                          ("cells", "LongLong"), ("mesh", "String")):
            f.append(QgsField(name, compat.field_type(typ)))
    return f


def grid_features(grid: meshes.Grid, cells: bool, fields: QgsFields, feedback=None):
    """Features of the grid: one outline, or one polygon per cell (row-major, from the north-west)."""
    xmin, ymin, xmax, ymax = grid.bbox_albers
    if not cells:
        f = QgsFeature(fields)
        f.setGeometry(_poly(xmin, ymin, xmax, ymax))
        f.setAttributes([grid.grid_id, grid.resolution, grid.cols, grid.rows, grid.cells, grid.mesh or ""])
        yield f
        return
    r = grid.resolution
    for row in range(grid.rows):
        if feedback is not None:
            if feedback.isCanceled():
                return
            feedback.setProgress(100.0 * row / max(grid.rows, 1))
        y1 = ymax - row * r
        for col in range(grid.cols):
            x0 = xmin + col * r
            f = QgsFeature(fields)
            f.setGeometry(_poly(x0, y1 - r, x0 + r, y1))
            f.setAttributes([row, col, f"{grid.grid_id}:R{row:04d}C{col:04d}"])
            yield f


def grid_layer(grid: meshes.Grid, cells: bool | None = None) -> QgsVectorLayer:
    """A memory layer with the grid (its cells when there are few enough, else its outline)."""
    if cells is None:
        cells = grid.cells <= MAX_PREVIEW_CELLS
    fields = grid_fields(cells)
    layer = _memory_layer(f"grid {grid.grid_id}" + (" (cells)" if cells else ""), fields)
    layer.dataProvider().addFeatures(list(grid_features(grid, cells, fields)))
    layer.updateExtents()
    return layer


def tile_fields() -> QgsFields:
    f = QgsFields()
    f.append(QgsField("tile", compat.field_type("String")))
    f.append(QgsField("h", compat.field_type("Int")))
    f.append(QgsField("v", compat.field_type("Int")))
    f.append(QgsField("level", compat.field_type("String")))
    return f


def tile_features(level: str, ids: list[str], fields: QgsFields):
    for t in ids:
        h, v = meshes.parse_tile_id(t)
        f = QgsFeature(fields)
        f.setGeometry(_poly(*meshes.tile_bounds(level, t)))
        f.setAttributes([t, h, v, level])
        yield f


def tiles_layer(level: str, ids: list[str] | None = None) -> QgsVectorLayer:
    """A memory layer with BDC tiles (all the tiles of the level when ``ids`` is None)."""
    ids = meshes.existing_tiles(level) if ids is None else ids
    fields = tile_fields()
    layer = _memory_layer(f"BDC {level} tiles", fields)
    layer.dataProvider().addFeatures(list(tile_features(level, ids, fields)))
    layer.updateExtents()
    return layer


#: Above this many cells the grid GeoTIFF is refused (4 bytes a cell; 200 million cells is 800 MB uncompressed).
MAX_RASTER_CELLS = 200_000_000


def write_grid_raster(grid: meshes.Grid, path: str) -> str:
    """Write the grid as a GeoTIFF in BDC Albers: one Int32 band ``cell_id`` = row · cols + col, from the north-west.

    The file has the cells DisSCube would write its variables on (same transform, size and CRS), so it can serve as
    the template or mask of a grid before any data is aggregated on it. Written by rows with GDAL (part of QGIS).
    """
    import numpy as np
    from osgeo import gdal, osr

    if grid.cells > MAX_RASTER_CELLS:
        raise ValueError(f"{grid.cells:,} cells is too many for a grid GeoTIFF (limit {MAX_RASTER_CELLS:,}); "
                         "use a coarser resolution")
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    xmin, _ymin, _xmax, ymax = grid.bbox_albers
    ds = gdal.GetDriverByName("GTiff").Create(path, grid.cols, grid.rows, 1, gdal.GDT_Int32,
                                              options=["COMPRESS=DEFLATE", "TILED=YES", "PREDICTOR=2"])
    if ds is None:
        raise OSError(f"GDAL could not create {path}")
    ds.SetGeoTransform((xmin, grid.resolution, 0.0, ymax, 0.0, -grid.resolution))
    srs = osr.SpatialReference()
    if srs.ImportFromEPSG(10857) != 0:
        srs.ImportFromProj4(albers.PROJ)
    ds.SetProjection(srs.ExportToWkt())
    band = ds.GetRasterBand(1)
    band.SetDescription("cell_id")
    ds.SetMetadata({"grid": grid.grid_id, "resolution": f"{grid.resolution:g}", "mesh": grid.mesh or "",
                    "cell_id": "row * cols + col, row 0 at the north, col 0 at the west"})
    step = max(1, 4_000_000 // max(grid.cols, 1))
    cols = np.arange(grid.cols, dtype="int64")
    for r0 in range(0, grid.rows, step):
        r1 = min(grid.rows, r0 + step)
        rows = np.arange(r0, r1, dtype="int64")[:, None]
        band.WriteArray((rows * grid.cols + cols).astype("int32"), 0, r0)
    band.FlushCache()
    ds = None
    return path
