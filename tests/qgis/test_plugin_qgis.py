"""Tests that need QGIS: the Processing algorithms, the panel and the call to an external DisSCube.

Run with the Python of QGIS, without a display:

    QT_QPA_PLATFORM=offscreen PYTHONPATH=/usr/share/qgis/python/plugins python3 -m pytest tests/qgis

``DISSCUBE_PYTHON`` points at a Python with DisSCube installed (for the validate and run tests); without it those
tests are skipped.
"""

from __future__ import annotations

import os
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

qgis = pytest.importorskip("qgis.core")

from qgis.core import QgsApplication, QgsProject, QgsVectorLayer  # noqa: E402
from qgis.testing import start_app  # noqa: E402

APP = start_app()

from qgis.testing.mocked import get_iface  # noqa: E402

from disscube_qgis.core import meshes, tomlio  # noqa: E402

FIX = ROOT / "tests" / "fixtures" / "disscube-grids"
DISSCUBE_PYTHON = os.environ.get("DISSCUBE_PYTHON", "")
_KEEP: list = []


@pytest.fixture(scope="module")
def processing_ready():
    from processing.core.Processing import Processing

    Processing.initialize()
    from disscube_qgis.processing_provider.provider import DisSCubeProvider

    prov = DisSCubeProvider()
    QgsApplication.processingRegistry().addProvider(prov)
    yield prov
    reg = QgsApplication.processingRegistry()
    if reg.providerById("disscube") is not None:
        reg.removeProvider(reg.providerById("disscube"))


def test_create_grid_on_bdc_tiles(processing_ready, tmp_path):
    import processing

    toml = tmp_path / "para_5k.toml"
    r = processing.run("disscube:creategrid", {
        "EXTENT": "-58.90,-46.06,-9.85,2.64 [EPSG:4326]", "NAME": "para_5k", "MESH": 0, "RESOLUTION": 5280,
        "TO_TILES": True, "CELLS": False, "OUTPUT": "memory:", "TOML": str(toml)})
    assert r["CELL_COUNT"] == 300 * 280
    g = tomlio.load(toml).grid
    assert g.bbox_albers == (4419200.0, 10158400.0, 6003200.0, 11636800.0)
    assert meshes.check(g, "bdc-sm").ok


def test_create_grid_lonlat_matches_the_para_case(processing_ready, tmp_path):
    """Mesh albers0 from the extent of the para case gives the grid DisSCube makes from that case."""
    import processing

    toml = tmp_path / "para.toml"
    processing.run("disscube:creategrid", {
        "EXTENT": "-58.90,-46.06,-9.85,2.64 [EPSG:4326]", "NAME": "para", "MESH": 3, "RESOLUTION": 5000,
        "TO_TILES": False, "CELLS": False, "OUTPUT": "memory:", "TOML": str(toml)})
    mine = tomlio.load(toml).grid
    case = tomlio.load(FIX / "para__sources.toml").grid
    assert mine.toml_table() == case.toml_table()
    assert mine.bbox_albers == case.bbox_albers and mine.grid_id == "para/5km"


def test_cells_output(processing_ready):
    import processing

    r = processing.run("disscube:creategrid", {
        "EXTENT": "4419200,4630400,10158400,10369600 [EPSG:10857]", "NAME": "t", "MESH": 0, "RESOLUTION": 5280,
        "TO_TILES": False, "CELLS": True, "OUTPUT": "memory:"})
    assert r["OUTPUT"].featureCount() == 40 * 40


def test_bdc_tiles(processing_ready):
    import processing

    r = processing.run("disscube:bdctiles", {"LEVEL": 0, "OUTPUT": "memory:"})
    assert r["OUTPUT"].featureCount() == 871
    r = processing.run("disscube:bdctiles", {"EXTENT": "-58.90,-46.06,-9.85,2.64 [EPSG:4326]", "LEVEL": 0,
                                             "OUTPUT": "memory:"})
    assert 0 < r["OUTPUT"].featureCount() < 871


def test_check_grid(processing_ready):
    import processing

    assert processing.run("disscube:checkgrid", {"TOML": str(FIX / "amazonia_legal__prodes.toml"), "MESH": 0})["NESTS"] == 0
    assert processing.run("disscube:checkgrid", {"TOML": str(FIX / "amazonia_legal__prodes.toml"), "MESH": 3})["NESTS"] == 1


def test_grid_from_a_raster(tmp_path):
    """A GeoTIFF on the grid of the open-lucc-workflow (br_5km) is read back as that grid."""
    from osgeo import gdal, osr

    from disscube_qgis import qgis_util
    from qgis.core import QgsRasterLayer

    path = str(tmp_path / "br_5km.tif")
    ds = gdal.GetDriverByName("GTiff").Create(path, 1040, 900, 1, gdal.GDT_Byte)
    ds.SetGeoTransform((2465600.0, 5280.0, 0, 12112000.0, 0, -5280.0))
    srs = osr.SpatialReference()
    srs.ImportFromProj4(meshes.albers.PROJ)
    ds.SetProjection(srs.ExportToWkt())
    ds = None
    g = qgis_util.grid_from_raster(QgsRasterLayer(path, "br"), "br_5km")
    assert (g.cols, g.rows, g.mesh) == (1040, 900, "bdc-sm")


@pytest.fixture
def dock():
    from disscube_qgis.ui.dock import DisSCubeDock

    iface = get_iface()
    d = DisSCubeDock(iface)
    yield d
    d.close()


def test_panel_builds_a_file(dock, tmp_path):
    from disscube_qgis.core import checks

    dock.name_edit.setText("ilha")
    from disscube_qgis.ui.dock import AREA_MODES

    dock.area_mode.setCurrentIndex([k for k, _ in AREA_MODES].index("lonlat"))
    dock.area_text_edit.setText("-44.35, -2.62, -44.20, -2.47")
    dock.res_combo.setCurrentIndex(dock.res_combo.findData(300.0))
    g = dock.fit_grid()
    assert g is not None and meshes.check(g, "bdc-sm").ok and g.resolution == 300.0
    dock.recipe_combo.setCurrentIndex(dock.recipe_combo.findData("mapbiomas-l1"))
    dock.recipe_arg.setText("2000, 2020")
    dock.add_recipe()
    dock.recipe_combo.setCurrentIndex(dock.recipe_combo.findData("prodes"))
    dock.recipe_arg.setText("2008 2024")
    dock.add_recipe()
    assert dock.source_list.count() == 2 and dock.derive_list.count() == 3
    probs = dock.refresh_preview()
    assert [p for p in probs if p.level == "error"] == []
    path = tmp_path / "ilha.toml"
    assert dock._write(str(path))
    p = tomlio.load(path)
    assert p.grid.name == "ilha" and p.grid.mesh == "bdc-sm"
    assert checks.errors(p) == []


def test_panel_same_grid_as_a_file(dock):
    dock.area_mode.setCurrentIndex(6)   # toml
    dock.toml_widget.setFilePath(str(FIX / "br163__prodes.toml"))
    g = dock.fit_grid()
    assert g.grid_id == "br163/500m"


def test_panel_opens_and_saves_a_case(dock, tmp_path):
    dock.open_file(str(FIX / "para__sources.toml"))
    assert dock.source_list.count() == 2 and dock.derive_list.count() == 2
    out = tmp_path / "copy.toml"
    assert dock._write(str(out))
    assert tomlio.parse(out.read_text()) == tomlio.parse((FIX / "para__sources.toml").read_text())


def test_show_grid_adds_layers(dock):
    dock.area_mode.setCurrentIndex(4)   # tiles
    dock.area_text_edit.setText("019015 020015")
    dock.fit_grid()
    before = len(QgsProject.instance().mapLayers())
    dock.show_grid()
    layers = list(QgsProject.instance().mapLayers().values())
    assert len(layers) == before + 2
    cells = [lyr for lyr in layers if isinstance(lyr, QgsVectorLayer) and "(cells)" in lyr.name()]
    assert cells and cells[0].featureCount() == 40 * 20


def test_forms_round_trip():
    from disscube_qgis.ui.forms import DeriveDialog, SourceDialog

    s = SourceDialog("prodes", {"id": "prodes_{year}", "years": [2008, 2024], "codes": {"forest": 1, "water": 4}})
    s._accept()
    assert s.result_data == {"id": "prodes_{year}", "type": "prodes", "years": [2008, 2024],
                             "codes": {"forest": 1, "water": 4}}
    d = DeriveDialog({"target": "f", "source": "prodes_{year}", "operator": "percentage", "class_code": [1, 2],
                      "params": {"subcells": 64}}, ["prodes_{year}"])
    d._accept()
    assert d.result_data["class_code"] == [1, 2] and d.result_data["params"] == {"subcells": 64}
    assert d.result_data["operator"] == "percentage"


def _wait(proc, timeout_ms=600_000):
    from qgis.PyQt.QtCore import QEventLoop, QTimer

    loop = QEventLoop()
    result = {}

    def done(code, out):
        result.update(code=code, out=out)
        loop.quit()

    proc.done.connect(done)
    QTimer.singleShot(timeout_ms, loop.quit)
    loop.exec()
    return result


@pytest.mark.skipif(not DISSCUBE_PYTHON, reason="DISSCUBE_PYTHON not set")
def test_external_validate(tmp_path):
    from disscube_qgis.bridge import disscube_cli

    f = tmp_path / "p.toml"
    tomlio.dump(tomlio.load(FIX / "para__sources.toml"), f)
    proc = disscube_cli.DisscubeProcess()
    proc.start(["validate", f.name, "--json"], cwd=str(tmp_path), interpreter=DISSCUBE_PYTHON)
    r = _wait(proc)
    assert r["code"] == 0 and disscube_cli.parse_json_tail(r["out"])["status"] == "ok"


@pytest.mark.skipif(not DISSCUBE_PYTHON, reason="DISSCUBE_PYTHON not set")
def test_external_run_on_a_local_raster(tmp_path):
    """A full run, offline: a small classified raster as a file source on a bdc-sm grid, then the GeoTIFF."""
    import numpy as np
    from osgeo import gdal, osr

    from disscube_qgis.bridge import disscube_cli
    from disscube_qgis.core import build

    # 2 x 2 cells of 5280 m on the BDC tiles, a 30 m raster under them
    x0, y1 = 4419200.0, 11636800.0
    n = int(2 * 5280 / 30)
    src = tmp_path / "classes.tif"
    ds = gdal.GetDriverByName("GTiff").Create(str(src), n, n, 1, gdal.GDT_Byte)
    ds.SetGeoTransform((x0, 30.0, 0, y1, 0, -30.0))
    srs = osr.SpatialReference()
    srs.ImportFromProj4(meshes.albers.PROJ)
    ds.SetProjection(srs.ExportToWkt())
    a = np.ones((n, n), dtype="uint8")
    a[:, n // 2:] = 2
    ds.GetRasterBand(1).WriteArray(a)
    ds.GetRasterBand(1).SetNoDataValue(0)
    ds = None

    g = meshes.fit_albers("t", (x0, y1 - 2 * 5280, x0 + 2 * 5280, y1), 5280.0, "bdc-sm")
    p = build.new_pipeline(g, "test")
    p.sources.append(tomlio.Item({"id": "cls", "type": "file", "path": "classes.tif"}))
    p.derives.append(tomlio.Item({"target": "share2", "source": "cls", "operator": "percentage", "class_code": 2}))
    f = tmp_path / "p.toml"
    tomlio.dump(p, f)
    proc = disscube_cli.DisscubeProcess()
    proc.start(["run", f.name, "--workspace", "ws", "--output", "out.tif"], cwd=str(tmp_path),
               interpreter=DISSCUBE_PYTHON)
    r = _wait(proc)
    assert r["code"] == 0, r["out"]
    out = gdal.Open(str(tmp_path / "out.tif"))
    v = out.GetRasterBand(1).ReadAsArray()
    assert out.GetGeoTransform() == (x0, 5280.0, 0.0, y1, 0.0, -5280.0)
    assert np.allclose(v, [[0, 1], [0, 1]])
    assert disscube_cli.run_record(tmp_path / "ws")["grid"] == "t"


def test_plugin_loads_and_unloads():
    """classFactory, initGui, open the panel, unload: the way QGIS drives a plugin."""
    import disscube_qgis

    reg = QgsApplication.processingRegistry()
    old = reg.providerById("disscube")      # the module fixture's provider, if it ran first
    if old is not None:
        reg.removeProvider(old)
    iface = get_iface()
    plugin = disscube_qgis.classFactory(iface)
    plugin.initGui()
    assert QgsApplication.processingRegistry().providerById("disscube") is not None
    plugin.toggle(True)
    assert plugin.dock is not None
    plugin.unload()
    assert QgsApplication.processingRegistry().providerById("disscube") is None


def test_flatpak_command_and_portal_paths():
    from disscube_qgis.bridge import disscube_cli as dc

    assert dc.is_portal_path("/run/user/1000/doc/26ac959f/python3.12")
    assert not dc.is_portal_path("/home/sergio/venvs/disscube/bin/python")
    assert dc.check_python_path("/run/user/1000/doc/26ac959f/python3.12")
    assert dc.check_python_path("/home/sergio/venvs/disscube/bin/python") is None
    prog, args = dc.command("/v/bin/python", "CODE", ["validate", "p.toml"], "/data/case", flatpak=True)
    assert prog == "flatpak-spawn"
    assert args[:2] == ["--host", "--watch-bus"] and "--directory=/data/case" in args
    assert args[-5:] == ["/v/bin/python", "-c", "CODE", "validate", "p.toml"]
    assert dc.command("/v/bin/python", "CODE", ["x"], "/d", flatpak=False) == ("/v/bin/python", ["-c", "CODE", "x"])


FAKE_SPAWN = r'''#!/usr/bin/env python3
"""Stands in for flatpak-spawn --host: the same options, run here."""
import os, sys
args = sys.argv[1:]
assert args.pop(0) == "--host", "the plugin must call flatpak-spawn --host"
env = {k: v for k, v in os.environ.items() if k not in ("PYTHONPATH", "PYTHONHOME")}
cwd = None
while args and args[0].startswith("--"):
    a = args.pop(0)
    if a.startswith("--directory="):
        cwd = a.split("=", 1)[1]
    elif a.startswith("--env="):
        k, v = a[6:].split("=", 1)
        env[k] = v
if cwd:
    os.chdir(cwd)
os.execve(args[0], args, env)
'''


@pytest.mark.skipif(not DISSCUBE_PYTHON, reason="DISSCUBE_PYTHON not set")
def test_validate_from_a_flatpak_qgis(tmp_path, monkeypatch):
    """In a Flatpak the plugin goes through flatpak-spawn --host, with the folder of the file as --directory."""
    from disscube_qgis.bridge import disscube_cli

    bindir = tmp_path / "bin"
    bindir.mkdir()
    spawn = bindir / "flatpak-spawn"
    spawn.write_text(FAKE_SPAWN)
    spawn.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bindir}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setenv("FLATPAK_ID", "org.qgis.qgis")
    case = tmp_path / "case"
    case.mkdir()
    tomlio.dump(tomlio.load(FIX / "br163__prodes.toml"), case / "p.toml")
    proc = disscube_cli.DisscubeProcess()
    lines = []
    proc.line.connect(lines.append)
    proc.start(["validate", "p.toml", "--json"], cwd=str(case), interpreter=DISSCUBE_PYTHON)
    r = _wait(proc)
    assert r["code"] == 0, r["out"]
    assert disscube_cli.parse_json_tail(r["out"])["status"] == "ok"
    assert lines[0].startswith("$ flatpak-spawn --host ")
    with pytest.raises(RuntimeError, match="Flatpak file dialog"):
        proc.start(["validate", "p.toml"], cwd=str(case), interpreter="/run/user/1000/doc/26ac959f/python3.12")


def _small_case(folder):
    """2 x 2 cells of 5280 m on the BDC tiles, over a 30 m raster: left half class 1, right half class 2."""
    import numpy as np
    from osgeo import gdal, osr

    from disscube_qgis.core import build

    x0, y1 = 4419200.0, 11636800.0
    n = int(2 * 5280 / 30)
    ds = gdal.GetDriverByName("GTiff").Create(str(folder / "classes.tif"), n, n, 1, gdal.GDT_Byte)
    ds.SetGeoTransform((x0, 30.0, 0, y1, 0, -30.0))
    srs = osr.SpatialReference()
    srs.ImportFromProj4(meshes.albers.PROJ)
    ds.SetProjection(srs.ExportToWkt())
    a = np.ones((n, n), dtype="uint8")
    a[:, n // 2:] = 2
    ds.GetRasterBand(1).WriteArray(a)
    ds.GetRasterBand(1).SetNoDataValue(0)
    ds = None
    g = meshes.fit_albers("small", (x0, y1 - 2 * 5280, x0 + 2 * 5280, y1), 5280.0, "bdc-sm")
    p = build.new_pipeline(g, "test")
    p.sources.append(tomlio.Item({"id": "cls", "type": "file", "path": "classes.tif"}))
    p.derives.append(tomlio.Item({"target": "share2", "source": "cls", "operator": "percentage", "class_code": 2}))
    return p


def _panel_run(dock, tmp_path):
    from disscube_qgis.bridge import disscube_cli

    disscube_cli.set_python(DISSCUBE_PYTHON)
    dock.pipeline = _small_case(tmp_path)
    assert dock._write(str(tmp_path / "small.toml"))
    dock.run()
    r = _wait(dock.proc)
    assert r["code"] == 0, r["out"]
    return [lyr for lyr in QgsProject.instance().mapLayers().values() if lyr.name() == "small"]


@pytest.mark.skipif(not DISSCUBE_PYTHON, reason="DISSCUBE_PYTHON not set")
def test_panel_run_adds_the_tif_to_the_map(dock, tmp_path):
    layers = _panel_run(dock, tmp_path)
    assert len(layers) == 1 and layers[0].isValid() and layers[0].bandCount() == 1
    assert "added to the map: small" in dock.log.toPlainText()
    # a second run replaces the layer instead of adding another
    dock.run()
    _wait(dock.proc)
    assert len([lyr for lyr in QgsProject.instance().mapLayers().values() if lyr.name() == "small"]) == 1


@pytest.mark.skipif(not DISSCUBE_PYTHON, reason="DISSCUBE_PYTHON not set")
def test_panel_run_from_a_flatpak_qgis_adds_the_tif(dock, tmp_path, monkeypatch):
    bindir = tmp_path / "bin"
    bindir.mkdir()
    spawn = bindir / "flatpak-spawn"
    spawn.write_text(FAKE_SPAWN)
    spawn.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bindir}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setenv("FLATPAK_ID", "org.qgis.qgis")
    case = tmp_path / "case"
    case.mkdir()
    layers = _panel_run(dock, case)
    assert layers and layers[-1].isValid()
    assert "flatpak-spawn --host" in dock.log.toPlainText()


def test_panel_says_when_the_output_is_not_seen(dock, tmp_path, monkeypatch):
    monkeypatch.setenv("FLATPAK_ID", "org.qgis.qgis")
    dock._run_done(0, str(tmp_path), "data/ws", "data/missing.tif")
    text = dock.log.toPlainText()
    assert "does not see" in text and "flatpak override --user --filesystem=" in text


def test_save_refuses_a_portal_path(dock, monkeypatch):
    from qgis.PyQt.QtWidgets import QMessageBox

    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: None)
    assert dock._write("/run/user/1000/doc/26ac959f/case.toml") is False


def test_run_without_variables_is_refused(dock, tmp_path, monkeypatch):
    from qgis.PyQt.QtWidgets import QMessageBox

    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.No)
    dock.pipeline = tomlio.Pipeline(grid=meshes.fit_albers("grid", (4.4192e6, 1.15312e7, 4.6304e6, 1.16368e7), 5280.0))
    dock._write(str(tmp_path / "grid.toml"))
    dock.run()
    assert not dock.proc.running()
    assert "no variables" in dock.log.toPlainText()


def test_run_record_with_no_derived_says_so(dock, tmp_path):
    ws = tmp_path / "data" / "grid"
    ws.mkdir(parents=True)
    (ws / "run.json").write_text('{"derived": []}')
    dock._run_done(0, str(tmp_path), "data/grid", "data/grid.tif")
    assert "no derived variables" in dock.log.toPlainText()


def test_grid_geotiff_has_the_cells_disscube_writes_on(tmp_path):
    """The grid GeoTIFF of the panel and of Processing: transform, size, CRS and cell_id values."""
    from osgeo import gdal

    from disscube_qgis import qgis_util

    g = meshes.fit_albers("small", (4419200.0, 11636800.0 - 3 * 5280, 4419200.0 + 2 * 5280, 11636800.0), 5280.0)
    path = str(tmp_path / "grid.tif")
    qgis_util.write_grid_raster(g, path)
    ds = gdal.Open(path)
    assert (ds.RasterXSize, ds.RasterYSize) == (2, 3)
    assert ds.GetGeoTransform() == (4419200.0, 5280.0, 0.0, 11636800.0, 0.0, -5280.0)
    assert ds.GetRasterBand(1).ReadAsArray().tolist() == [[0, 1], [2, 3], [4, 5]]
    assert ds.GetRasterBand(1).GetDescription() == "cell_id"
    assert "Albers" in ds.GetProjection() or "10857" in ds.GetProjection()


def test_create_grid_writes_a_geotiff(processing_ready, tmp_path):
    import processing
    from osgeo import gdal

    from disscube_qgis.processing_provider.provider import DisSCubeProvider

    if QgsApplication.processingRegistry().providerById("disscube") is None:   # unloaded by an earlier test
        _KEEP.append(DisSCubeProvider())     # keep a Python reference, or the provider is deleted
        QgsApplication.processingRegistry().addProvider(_KEEP[-1])

    tif = str(tmp_path / "g.tif")
    r = processing.run("disscube:creategrid", {
        "EXTENT": "4419200,4630400,10158400,10369600 [EPSG:10857]", "NAME": "g", "MESH": 0, "RESOLUTION": 5280,
        "TO_TILES": False, "CELLS": False, "OUTPUT": "memory:", "RASTER": tif})
    ds = gdal.Open(r["RASTER"])
    assert (ds.RasterXSize, ds.RasterYSize) == (40, 40)


@pytest.mark.skipif(not DISSCUBE_PYTHON, reason="DISSCUBE_PYTHON not set")
def test_panel_offers_the_grid_geotiff_when_there_are_no_variables(dock, tmp_path, monkeypatch):
    from osgeo import gdal
    from qgis.PyQt.QtWidgets import QMessageBox

    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Yes)
    small = _small_case(tmp_path)
    dock.pipeline = tomlio.Pipeline(grid=small.grid)
    assert dock._write(str(tmp_path / "grid.toml"))
    dock.run()
    tif = tmp_path / "data" / "small.tif"
    assert tif.exists()
    assert [lyr for lyr in QgsProject.instance().mapLayers().values() if lyr.name() == "small"]
    # same cells as a DisSCube run with a variable on the same grid
    dock.pipeline = small
    dock._write(str(tmp_path / "small.toml"))
    dock.output_edit.setText("data/with_vars.tif")
    dock.run()
    _wait(dock.proc)
    a, b = gdal.Open(str(tif)), gdal.Open(str(tmp_path / "data" / "with_vars.tif"))
    assert a.GetGeoTransform() == b.GetGeoTransform()
    assert (a.RasterXSize, a.RasterYSize) == (b.RasterXSize, b.RasterYSize)


def test_grid_geotiff_of_a_file_made_in_the_panel(tmp_path):
    """A grid-only file as the panel saved it (2,200 m over the map extent): 2491 x 2421 cells."""
    from osgeo import gdal

    from disscube_qgis import qgis_util

    p = tomlio.loads('schema = 1\n[grid]\nname = "grid"\ncrs = "EPSG:10857"\nresolution = 2200\n'
                     'bbox = [2558000.0, 7047600.0, 8038200.0, 12373800.0]\n')
    path = qgis_util.write_grid_raster(p.grid, str(tmp_path / "grid.tif"))
    ds = gdal.Open(path)
    assert (ds.RasterXSize, ds.RasterYSize) == (2491, 2421)
    assert int(ds.GetRasterBand(1).ReadAsArray(2490, 2420, 1, 1)[0, 0]) == 2491 * 2421 - 1
