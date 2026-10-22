# Changelog

## 0.1.1

- Runs on QGIS 4 (Qt 6, PyQt6): the panel failed to open with `Qt has no attribute 'TextSelectableByMouse'`. Every
  Qt enum is now written in full (`Qt.TextInteractionFlag.TextSelectableByMouse`), which PyQt5 5.15 also accepts;
  `exec_()` became `exec()`; the QGIS names that moved (Processing source and number types, WKB type, sink flags,
  field types, layer filters) are looked up in `disscube_qgis/compat.py`. `metadata.txt` declares
  `supportsQt6=True`.
- Tested on QGIS 3.34.4 (Qt 5) and QGIS 4.2.3 (Qt 6).

## 0.1.0 (unreleased)

First version.

- Grids on four meshes: the tiles of the BDC Grid V2 (`bdc-sm`, `bdc-md`, `bdc-lg`; resolutions that divide the tile)
  and `albers0`, what DisSCube does with a lon/lat `[grid]`.
- Panel with the tabs Grid, Sources, Variables, File and run: the area from the map, a layer, selected features,
  BDC tiles, a lon/lat bbox, or the grid of an existing pipeline file or raster; preview layers of the grid and the
  tiles; forms for every source type and the derived variables of DisSCube 0.6.0; seven recipes copied from
  `disscube-grids` v1.1.0; open and save pipeline files.
- Processing provider "DisSCube": Create DisSCube grid, BDC tiles of an area, Check grid nesting.
- Validate and run through a DisSCube installed outside QGIS (`QProcess`); the result GeoTIFF is added to the map
  and its SHA-256 written to the log.
