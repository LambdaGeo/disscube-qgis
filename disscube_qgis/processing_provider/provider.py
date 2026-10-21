"""Processing provider "DisSCube": the grid tools as Processing algorithms (toolbox, graphical modeler, batch)."""

from __future__ import annotations

import os

from qgis.core import (
    QgsFeatureSink,
    QgsProcessing,
    QgsProcessingAlgorithm,
    QgsProcessingException,
    QgsProcessingOutputNumber,
    QgsProcessingOutputString,
    QgsProcessingParameterBoolean,
    QgsProcessingParameterEnum,
    QgsProcessingParameterExtent,
    QgsProcessingParameterFeatureSink,
    QgsProcessingParameterFile,
    QgsProcessingParameterFileDestination,
    QgsProcessingParameterNumber,
    QgsProcessingParameterRasterLayer,
    QgsProcessingParameterString,
    QgsProcessingProvider,
    QgsWkbTypes,
)
from qgis.PyQt.QtGui import QIcon

from .. import qgis_util
from ..core import __version__, build, checks, meshes, tomlio

MESH_KEYS = list(meshes.MESHES)
LEVELS = list(meshes.TILE_LEVELS)
ICON = os.path.join(os.path.dirname(os.path.dirname(__file__)), "icon.png")


class _Base(QgsProcessingAlgorithm):
    def group(self):
        return "Grids"

    def groupId(self):
        return "grids"

    def createInstance(self):
        return type(self)()

    def icon(self):
        return QIcon(ICON)


class CreateGrid(_Base):
    EXTENT, NAME, MESH, RESOLUTION, TO_TILES, CELLS, OUTPUT, TOML = (
        "EXTENT", "NAME", "MESH", "RESOLUTION", "TO_TILES", "CELLS", "OUTPUT", "TOML")

    def name(self):
        return "creategrid"

    def displayName(self):
        return "Create DisSCube grid"

    def shortHelpString(self):
        return (
            "Fits a grid to an extent on one of the meshes DisSCube grids use, and writes the [grid] block of a "
            "pipeline file.<br><br>"
            "<b>bdc-sm / bdc-md / bdc-lg</b>: cells aligned with the tiles of the BDC Grid V2 (105.6, 211.2, 422.4 km); "
            "the resolution must divide the tile (5280 m gives 20 x 20 cells per small tile). The [grid] is written in "
            "BDC Albers (EPSG:10857).<br>"
            "<b>albers0</b>: what DisSCube does with a lon/lat [grid]: multiples of the resolution from the origin of "
            "BDC Albers. The [grid] is written in lon/lat, as DisSCube expects it.<br><br>"
            "The output layer has the outline of the grid, or every cell."
        )

    def initAlgorithm(self, config=None):
        self.addParameter(QgsProcessingParameterExtent(self.EXTENT, "Area"))
        self.addParameter(QgsProcessingParameterString(self.NAME, "Grid name", defaultValue="grid"))
        self.addParameter(QgsProcessingParameterEnum(self.MESH, "Mesh", options=MESH_KEYS,
                                                     defaultValue=MESH_KEYS.index(meshes.DEFAULT_MESH)))
        self.addParameter(QgsProcessingParameterNumber(self.RESOLUTION, "Resolution (m)",
                                                       QgsProcessingParameterNumber.Double, defaultValue=5280.0,
                                                       minValue=1.0))
        self.addParameter(QgsProcessingParameterBoolean(self.TO_TILES, "Extend to whole tiles", defaultValue=False))
        self.addParameter(QgsProcessingParameterBoolean(self.CELLS, "One polygon per cell (else the outline)",
                                                        defaultValue=False))
        self.addParameter(QgsProcessingParameterFeatureSink(self.OUTPUT, "Grid", QgsProcessing.TypeVectorPolygon))
        self.addParameter(QgsProcessingParameterFileDestination(self.TOML, "Pipeline file (TOML)", "TOML (*.toml)",
                                                                optional=True, createByDefault=False))
        self.addOutput(QgsProcessingOutputString("GRID_ID", "Grid id"))
        self.addOutput(QgsProcessingOutputNumber("CELL_COUNT", "Cells"))

    def processAlgorithm(self, parameters, context, feedback):
        name = self.parameterAsString(parameters, self.NAME, context).strip() or "grid"
        mesh_key = MESH_KEYS[self.parameterAsEnum(parameters, self.MESH, context)]
        res = self.parameterAsDouble(parameters, self.RESOLUTION, context)
        crs = self.parameterAsExtentCrs(parameters, self.EXTENT, context)
        extent = self.parameterAsExtent(parameters, self.EXTENT, context, crs)
        try:
            grid = qgis_util.fit_extent(name, extent, crs, res, mesh_key,
                                        self.parameterAsBool(parameters, self.TO_TILES, context))
        except ValueError as e:
            raise QgsProcessingException(str(e)) from e
        cells = self.parameterAsBool(parameters, self.CELLS, context)
        if cells and grid.cells > 2_000_000:
            raise QgsProcessingException(f"{grid.cells:,} cells is too many polygons; write the outline instead")
        fields = qgis_util.grid_fields(cells)
        sink, dest = self.parameterAsSink(parameters, self.OUTPUT, context, fields, QgsWkbTypes.Polygon,
                                          qgis_util.albers_crs())
        if sink is None:
            raise QgsProcessingException("cannot create the output layer")
        for f in qgis_util.grid_features(grid, cells, fields, feedback):
            sink.addFeature(f, QgsFeatureSink.FastInsert)
        for line in checks.grid_report(grid):
            feedback.pushInfo(line)
        out = {self.OUTPUT: dest, "GRID_ID": grid.grid_id, "CELL_COUNT": grid.cells}
        toml = self.parameterAsFileOutput(parameters, self.TOML, context)
        if toml:
            area = "extent given to the Processing algorithm 'Create DisSCube grid'"
            tomlio.dump(build.new_pipeline(grid, name, area), toml)
            feedback.pushInfo(f"pipeline file: {toml}")
            out[self.TOML] = toml
        return out


class BdcTiles(_Base):
    EXTENT, LEVEL, OUTPUT = "EXTENT", "LEVEL", "OUTPUT"

    def name(self):
        return "bdctiles"

    def displayName(self):
        return "BDC tiles of an area"

    def shortHelpString(self):
        return ("The tiles of the Brazil Data Cube Grid V2 (SM 105.6 km, MD 211.2 km, LG 422.4 km) that intersect the "
                "area, with their id (hhhvvv), h and v. Without an area, every tile of the level.")

    def initAlgorithm(self, config=None):
        self.addParameter(QgsProcessingParameterExtent(self.EXTENT, "Area", optional=True))
        self.addParameter(QgsProcessingParameterEnum(self.LEVEL, "Level", options=LEVELS, defaultValue=0))
        self.addParameter(QgsProcessingParameterFeatureSink(self.OUTPUT, "BDC tiles", QgsProcessing.TypeVectorPolygon))

    def processAlgorithm(self, parameters, context, feedback):
        level = LEVELS[self.parameterAsEnum(parameters, self.LEVEL, context)]
        if parameters.get(self.EXTENT):
            crs = self.parameterAsExtentCrs(parameters, self.EXTENT, context)
            extent = self.parameterAsExtent(parameters, self.EXTENT, context, crs)
            ids = meshes.tiles_covering(level, qgis_util.to_albers(extent, crs))
        else:
            ids = meshes.existing_tiles(level)
        fields = qgis_util.tile_fields()
        sink, dest = self.parameterAsSink(parameters, self.OUTPUT, context, fields, QgsWkbTypes.Polygon,
                                          qgis_util.albers_crs())
        for f in qgis_util.tile_features(level, ids, fields):
            sink.addFeature(f, QgsFeatureSink.FastInsert)
        feedback.pushInfo(f"{len(ids)} {level} tiles")
        return {self.OUTPUT: dest}


class CheckGrid(_Base):
    TOML, RASTER, MESH = "TOML", "RASTER", "MESH"

    def name(self):
        return "checkgrid"

    def displayName(self):
        return "Check grid nesting"

    def shortHelpString(self):
        return ("Says whether the grid of a pipeline file (TOML) or of a raster in BDC Albers nests in a mesh: the "
                "resolution divides the tile, and the corner lies a whole number of cells from the mesh origin. "
                "Lists the meshes it nests in.")

    def initAlgorithm(self, config=None):
        self.addParameter(QgsProcessingParameterFile(self.TOML, "Pipeline file (TOML)", extension="toml",
                                                     optional=True))
        self.addParameter(QgsProcessingParameterRasterLayer(self.RASTER, "or a raster", optional=True))
        self.addParameter(QgsProcessingParameterEnum(self.MESH, "Mesh", options=MESH_KEYS,
                                                     defaultValue=MESH_KEYS.index(meshes.DEFAULT_MESH)))
        self.addOutput(QgsProcessingOutputString("REPORT", "Report"))
        self.addOutput(QgsProcessingOutputNumber("NESTS", "Nests (1) or not (0)"))

    def processAlgorithm(self, parameters, context, feedback):
        path = self.parameterAsFile(parameters, self.TOML, context)
        raster = self.parameterAsRasterLayer(parameters, self.RASTER, context)
        try:
            if path:
                p = tomlio.load(path)
                if p.grid is None:
                    raise QgsProcessingException(f"{path} has no [grid]")
                grid = p.grid
            elif raster is not None:
                grid = qgis_util.grid_from_raster(raster, raster.name())
            else:
                raise QgsProcessingException("give a pipeline file or a raster")
        except ValueError as e:
            raise QgsProcessingException(str(e)) from e
        mesh_key = MESH_KEYS[self.parameterAsEnum(parameters, self.MESH, context)]
        c = meshes.check(grid, mesh_key)
        lines = [f"{mesh_key}: {'nests' if c.ok else 'does NOT nest'}"] + [f"  {x}" for x in c.lines]
        lines += checks.grid_report(grid)
        for line in lines:
            (feedback.pushInfo if c.ok or not line.startswith("  ") else feedback.reportError)(line)
        return {"REPORT": "\n".join(lines), "NESTS": 1 if c.ok else 0}


class DisSCubeProvider(QgsProcessingProvider):
    def id(self):
        return "disscube"

    def name(self):
        return "DisSCube"

    def longName(self):
        return f"DisSCube grids ({__version__})"

    def icon(self):
        return QIcon(ICON)

    def loadAlgorithms(self):
        for alg in (CreateGrid(), BdcTiles(), CheckGrid()):
            self.addAlgorithm(alg)
