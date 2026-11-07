# DisSCube plugin for QGIS

[![DOI](https://zenodo.org/badge/DOI/10.5281/zenodo.24033974.svg)](https://doi.org/10.5281/zenodo.24033974)

Build the grids and the pipeline files of [DisSCube](https://github.com/DisSModel/disscube) (Declarative spatial data
cubes) on the map.

A DisSCube pipeline is one TOML file: a `[grid]`, the sources (MapBiomas, PRODES, Brazil Data Cube, OpenStreetMap,
DEMs, local files) and the variables derived from them on the grid. Writing the `[grid]` by hand means projecting an
extent to BDC Albers, rounding it to the cells, and checking that the cells line up with the other grids of the
project. The plugin does that in QGIS, and writes a plain TOML file that runs with `disscube run`, with or without
the plugin.

- **Grid**: choose the area (the map extent, a rectangle drawn on the map, a layer, the selected features, BDC tile
  ids, a lon/lat bbox, or the grid of an existing pipeline file or raster), a mesh and a resolution that nests in it.
  The panel shows the grid size, the BDC tiles it covers and how many pixels each common source will read; *Show on
  map* adds the grid (its cells, when there are fewer than 50,000) and its tiles as layers. *Save grid as GeoTIFF…*
  writes the grid alone (band `cell_id`), with the cells DisSCube writes its variables on.
- **Sources and variables**: a form for every source type and for the derived variables of DisSCube 0.6.0, with the
  operators and their parameters; ready-made recipes copied from cases that ran
  ([disscube-grids](https://github.com/LambdaGeo/disscube-grids) v1.1.0): MapBiomas dominant class and level 1,
  forest and pasture shares, PRODES shares, BDC NDVI (MODIS or Landsat), distance to the municipal seats of IBGE.
- **File and run**: the file as it will be saved, the problems the plugin finds, and, with a DisSCube installed
  outside QGIS, *Validate* and *Run*; the result GeoTIFF is added to the map and its SHA-256 written to the log.
- **Processing**: *Create DisSCube grid*, *BDC tiles of an area* and *Check grid nesting*, in the toolbox, the
  graphical modeler and batch mode.

## Meshes

All grids are in BDC Albers (EPSG:10857). The plugin knows four meshes:

| Mesh | Cells counted from | Resolutions | `[grid]` written as |
|---|---|---|---|
| `bdc-sm` (default) | the corner of the BDC Grid V2 tiles, x = 2,624,000, y = 11,953,600 | divisors of 105,600 m: 30, 50, 100, 300, …, 5,280 (20 × 20 cells per tile), 10,560 (10 × 10) | `crs` and `bbox` in BDC Albers |
| `bdc-md`, `bdc-lg` | same corner | divisors of 211,200 m and 422,400 m | `crs` and `bbox` in BDC Albers |
| `albers0` | the origin of the projection (0, 0) | any | `bbox` in lon/lat, no `crs`: what DisSCube does by default |

The BDC tiles follow a closed formula, checked against every tile of the BDC Grid V2 shapefiles bundled with
DisSCube (871 SM, 242 MD, 75 LG): `xmin = 2,624,000 + h · L`, `ymax = 11,953,600 − v · L`, for the tile `hhhvvv`.
A grid on `bdc-sm` at 5,280 m has the cells of the
[open-lucc-workflow](https://github.com/LambdaGeo/open-lucc-workflow) grid `br_5km`. A grid on `albers0` does not
line up with the tiles (the tile corner is 89,600 m east of a multiple of 105,600 m from zero), and 5,000 m or
1,000 m do not divide a tile.

## Install

The plugin needs QGIS 3.34 or later (QGIS 4 included) and nothing else.

1. Download `disscube_qgis-<version>.zip` from the releases (or build it, below).
2. QGIS → *Plugins* → *Manage and Install Plugins* → *Install from ZIP*.
3. *Raster* → *DisSCube* → *DisSCube grids and pipelines* opens the panel.

To validate and run pipelines from the panel, install DisSCube in a Python environment of its own (not the Python of
QGIS) and give that Python in *File and run* → *Python with DisSCube*:

```bash
python -m venv ~/venvs/disscube
~/venvs/disscube/bin/pip install "disscube[bdc,netcdf]==0.6.0"
# then, in the panel: ~/venvs/disscube/bin/python   (Windows: ...\venvs\disscube\Scripts\python.exe)
```

**QGIS from Flathub** (`org.qgis.qgis`) runs in a sandbox. The plugin then starts DisSCube on the computer with
`flatpak-spawn --host`, which needs one permission, given once in a terminal (then restart QGIS):

```bash
flatpak override --user --talk-name=org.freedesktop.Flatpak org.qgis.qgis
```

Type the path of the Python (`/home/<you>/venvs/disscube/bin/python`) or pick it with the plugin's file dialog; a
path under `/run/user/<uid>/doc/…` is a copy made by the Flatpak file portal and is refused.

*Check* shows the DisSCube version found. The plugin runs `python -c "from disscube.cli import main; …" run FILE
--workspace … --output …` in the folder of the file; a run can be cancelled.

## Example

[`examples/brasil_2200m_seats.toml`](examples/brasil_2200m_seats.toml): a 2,200 m grid over Brazil on the BDC SM
tiles (2491 x 2421 cells) with one light variable, the distance to the municipal seats of IBGE. It was made and run
from the panel; a good first run before satellite sources.

## What the file looks like

```toml
# Pará — MapBiomas and PRODES, 5.28 km
#
#     disscube validate para_5k.toml
#     disscube run para_5k.toml --workspace data/para_5k --output data/para_5k.tif

schema = 1
name = "Pará — MapBiomas and PRODES, 5.28 km"

# Grid made with the DisSCube plugin for QGIS 0.1.5.
# Mesh bdc-sm: BDC Grid V2 SM tiles of 105.6 km, 20 x 20 cells per tile; tiles h 017–031, v 003–016.
# Area: lon/lat bbox [-58.9, -9.85, -46.06, 2.64]
[grid]
name = "para_5k"
crs = "EPSG:10857"
resolution = 5280
bbox = [4419200.0, 10158400.0, 6003200.0, 11636800.0]   # 300 x 280 cells

# PRODES (Legal Amazon): situation at the end of each year; years are separable from 2007 on
[[source]]
id = "prodes_{year}"
type = "prodes"
years = [2008, 2024]

[[derive]]
target = "prodes_deforested_pct"
source = "prodes_{year}"
operator = "percentage"
class_code = 2
```

Opening a file written by hand and saving it again keeps its content but not its comments: the panel warns, and
*Save as* keeps the original.

## How it is built

```
disscube_qgis/
  core/          no QGIS: BDC Albers in pure Python, meshes and grids, TOML read/write, checks, recipes
    data/        bdc_tiles.json (tile ids) and disscube_catalog.json (source fields and operators of DisSCube 0.6.0)
    _vendor/     tomli 2.2.1 (MIT), to read TOML on the Pythons older than 3.11 that some QGIS builds ship
  processing_provider/   the three Processing algorithms
  ui/            the panel and the source and variable forms
  bridge/        DisSCube run through QProcess
```

The plugin does not import DisSCube. What it needs to know about pipeline files is generated from the DisSCube it is
pinned to by `scripts/build_catalog.py`; the tests regenerate it and fail when a new DisSCube adds a field or an
operator. The tile ids come from `scripts/build_bdc_tiles.py`, which also checks the tile formula.

## Development

```bash
# the core, without QGIS (standard library only; with disscube installed it is also checked against DisSCube)
pip install pytest disscube==0.6.0 pyproj pyshp
pytest tests --ignore=tests/qgis

# inside QGIS, without a display; DISSCUBE_PYTHON enables the validate and run tests
QT_QPA_PLATFORM=offscreen PYTHONPATH=/usr/share/qgis/python:/usr/share/qgis/python/plugins \
  DISSCUBE_PYTHON=~/venvs/disscube/bin/python python3 -m pytest tests/qgis

python scripts/package.py      # dist/disscube_qgis-<version>.zip
```

The QGIS tests cover the Processing algorithms, the panel (a grid from a lon/lat bbox, recipes, saving; the grid of
another file; opening and saving a case unchanged; the preview layers), the forms, loading and unloading the plugin,
and a full offline `disscube run` on a small raster through the panel's process runner.

## Not yet

- A mask of the cells inside a polygon (the grid is a rectangle).
- Grids in a CRS other than BDC Albers (write the `[grid]` by hand; the plugin refuses to open such a file).
- Keeping the comments of a file written by hand.
- Translations (the interface is in English).

## Licence

MIT. `disscube_qgis/core/_vendor/tomli` is tomli 2.2.1 by Taneli Hukkinen, MIT (its licence is next to it).

## Citation

Costa, S. S. (2026). *DisSCube plugin for QGIS: grids and pipeline files for declarative spatial data cubes* (Version v0.1.5) [Computer software]. Zenodo. https://doi.org/10.5281/zenodo.24033974
