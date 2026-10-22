# Changelog

## 0.1.3

- After a run, the GeoTIFF was added to the map only when QGIS could see it, and nothing was said otherwise. The
  panel now logs the layer it added, or why it could not: the output is not visible to QGIS (with the Flatpak
  permission to give), or QGIS could not open it. A new run replaces the layer of the previous one.
- Open, save and "same grid as a file" use Qt's own file dialog, and saving to a Flatpak portal path is refused:
  DisSCube writes its data next to the file, which a portal folder does not allow.
- Before a run, the panel checks that QGIS can write in the folder of the file.

## 0.1.2

- QGIS from Flathub (`org.qgis.qgis`) runs in a sandbox, where the Python of the computer cannot be started and the
  native file dialog hands back a copy under `/run/user/<uid>/doc/…` (with the symlink of a venv's `python`
  resolved to the system Python). The plugin now starts DisSCube with `flatpak-spawn --host` when QGIS is a Flatpak,
  opens Qt's own file dialog for the Python, refuses portal paths with an explanation, and tells how to give the
  permission it needs (`flatpak override --user --talk-name=org.freedesktop.Flatpak org.qgis.qgis`).
- Cancelling a run sends SIGTERM first (passed on by `flatpak-spawn` to the program), then SIGKILL after 5 s.

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
