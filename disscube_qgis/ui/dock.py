"""The DisSCube panel: build a grid on the map, add sources and variables, save the TOML, validate and run it."""

from __future__ import annotations

import os
import re
from pathlib import Path

from qgis.core import (
    Qgis,
    QgsProject,
    QgsRasterLayer,
    QgsRectangle,
    QgsVectorLayer,
)
from qgis.gui import QgsFileWidget, QgsMapLayerComboBox, QgsMapToolExtent
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtGui import QColor, QFont, QFontDatabase
from qgis.PyQt.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDockWidget,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from .. import compat, qgis_util
from ..bridge import disscube_cli
from ..core import build, catalog, checks, meshes, recipes, tomlio
from .forms import DeriveDialog, SourceDialog

AREA_MODES = [
    ("canvas", "Map canvas extent"),
    ("draw", "Rectangle drawn on the map"),
    ("layer", "Extent of a layer"),
    ("selected", "Selected features of a layer"),
    ("tiles", "BDC tiles (ids)"),
    ("lonlat", "Lon/lat bbox"),
    ("toml", "Same grid as a pipeline file"),
    ("raster", "Same grid as a raster"),
]


def _mono() -> QFont:
    return QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)


def _slug(text: str) -> str:
    s = re.sub(r"[^0-9A-Za-z_]+", "_", text.strip()).strip("_").lower()
    return s or "grid"


class DisSCubeDock(QDockWidget):
    def __init__(self, iface, parent=None):
        super().__init__("DisSCube", parent)
        self.setObjectName("DisSCubeDock")
        self.iface = iface
        self.pipeline = tomlio.Pipeline()
        self.path: str | None = None
        self.area_text = ""
        self.drawn: tuple[QgsRectangle, object] | None = None
        self.prev_tool = None
        self.extent_tool = None
        self.proc = disscube_cli.DisscubeProcess(self)
        self.proc.line.connect(self._log)
        self.proc.done.connect(self._proc_done)
        self._after = None

        host = QWidget()
        lay = QVBoxLayout(host)
        lay.addLayout(self._file_bar())
        self.tabs = QTabWidget()
        self.tabs.addTab(self._grid_tab(), "Grid")
        self.tabs.addTab(self._sources_tab(), "Sources")
        self.tabs.addTab(self._derive_tab(), "Variables")
        self.tabs.addTab(self._run_tab(), "File and run")
        self.tabs.currentChanged.connect(self._tab_changed)
        lay.addWidget(self.tabs)
        self.setWidget(host)
        self._area_mode_changed()
        self._mesh_changed()
        self._refresh_lists()

    # ── file bar ────────────────────────────────────────────────────────────
    def _file_bar(self):
        h = QHBoxLayout()
        for text, slot in (("New", self.new_file), ("Open…", self.open_file), ("Save", self.save_file),
                           ("Save as…", self.save_file_as)):
            b = QPushButton(text)
            b.clicked.connect(slot)
            h.addWidget(b)
        self.file_label = QLabel("(not saved)")
        self.file_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        h.addWidget(self.file_label, 1)
        return h

    # ── grid tab ────────────────────────────────────────────────────────────
    def _grid_tab(self):
        w = QWidget()
        v = QVBoxLayout(w)
        form = QFormLayout()
        self.title_edit = QLineEdit()
        self.title_edit.setPlaceholderText("title of the pipeline (name = …)")
        form.addRow("Title", self.title_edit)
        self.name_edit = QLineEdit("grid")
        form.addRow("Grid name", self.name_edit)

        self.area_mode = QComboBox()
        for key, label in AREA_MODES:
            self.area_mode.addItem(label, key)
        self.area_mode.currentIndexChanged.connect(self._area_mode_changed)
        form.addRow("Area", self.area_mode)
        self.layer_combo = QgsMapLayerComboBox()
        self.layer_combo.setFilters(compat.layer_filters("VectorLayer", "RasterLayer"))
        form.addRow("Layer", self.layer_combo)
        self.area_text_edit = QLineEdit()
        form.addRow("Values", self.area_text_edit)
        self.toml_widget = QgsFileWidget()
        self.toml_widget.setFilter("Pipeline (*.toml)")
        self.toml_widget.setOptions(QFileDialog.Option.DontUseNativeDialog)
        form.addRow("File", self.toml_widget)
        self.draw_button = QPushButton("Draw on the map")
        self.draw_button.clicked.connect(self._start_draw)
        form.addRow("", self.draw_button)

        self.mesh_combo = QComboBox()
        for key, m in meshes.MESHES.items():
            self.mesh_combo.addItem(f"{key} — {m.label}", key)
        self.mesh_combo.setCurrentIndex(list(meshes.MESHES).index(meshes.DEFAULT_MESH))
        self.mesh_combo.currentIndexChanged.connect(self._mesh_changed)
        form.addRow("Mesh", self.mesh_combo)
        self.res_combo = QComboBox()
        self.res_combo.setEditable(True)
        form.addRow("Resolution (m)", self.res_combo)
        self.to_tiles = QCheckBox("Extend to whole tiles")
        form.addRow("", self.to_tiles)
        v.addLayout(form)

        h = QHBoxLayout()
        for text, slot in (("Fit grid", self.fit_grid), ("Show on map", self.show_grid),
                           ("All BDC tiles", self.show_all_tiles)):
            b = QPushButton(text)
            b.clicked.connect(slot)
            h.addWidget(b)
        v.addLayout(h)
        self.grid_report = QPlainTextEdit()
        self.grid_report.setReadOnly(True)
        self.grid_report.setFont(_mono())
        v.addWidget(self.grid_report, 1)
        return w

    def _area_mode_changed(self):
        mode = self.area_mode.currentData()
        self.layer_combo.setEnabled(mode in ("layer", "selected", "raster"))
        self.area_text_edit.setEnabled(mode in ("tiles", "lonlat"))
        self.toml_widget.setEnabled(mode == "toml")
        self.draw_button.setEnabled(mode == "draw")
        hints = {"tiles": "ids hhhvvv separated by spaces or commas, e.g. 019015 020015",
                 "lonlat": "lon_min, lat_min, lon_max, lat_max (WGS84)"}
        self.area_text_edit.setPlaceholderText(hints.get(mode, ""))
        if mode == "raster":
            self.layer_combo.setFilters(compat.layer_filters("RasterLayer"))
        else:
            self.layer_combo.setFilters(compat.layer_filters("VectorLayer", "RasterLayer"))
        fixed = mode in ("toml", "raster")
        self.mesh_combo.setEnabled(not fixed)
        self.res_combo.setEnabled(not fixed)
        self.to_tiles.setEnabled(not fixed and self.mesh_combo.currentData() != "albers0")

    def _mesh_changed(self):
        key = self.mesh_combo.currentData()
        current = self.res_combo.currentText()
        self.res_combo.clear()
        rs = meshes.resolutions(key)
        m = meshes.mesh(key)
        for r in rs:
            label = f"{r:g}"
            if m.tile_size:
                per = int(round(m.tile_size / r))
                label += f"   ({per} × {per} per tile)"
            self.res_combo.addItem(label, r)
        default = 5280.0 if m.tile_size else 5000.0
        target = current.split()[0] if current else f"{default:g}"
        idx = self.res_combo.findText(target, Qt.MatchFlag.MatchStartsWith)
        self.res_combo.setCurrentIndex(idx if idx >= 0 else max(0, self.res_combo.findText(f"{default:g}",
                                                                                            Qt.MatchFlag.MatchStartsWith)))
        self.to_tiles.setEnabled(key != "albers0" and self.area_mode.currentData() not in ("toml", "raster"))

    def _resolution(self) -> float:
        text = self.res_combo.currentText().split()[0].replace(",", ".")
        return float(text)

    def _start_draw(self):
        canvas = self.iface.mapCanvas()
        self.prev_tool = canvas.mapTool()
        self.extent_tool = QgsMapToolExtent(canvas)
        self.extent_tool.extentChanged.connect(self._drawn)
        canvas.setMapTool(self.extent_tool)
        self.iface.messageBar().pushInfo("DisSCube", "Drag a rectangle on the map.")

    def _drawn(self, rect: QgsRectangle):
        canvas = self.iface.mapCanvas()
        self.drawn = (QgsRectangle(rect), canvas.mapSettings().destinationCrs())
        if self.prev_tool is not None:
            canvas.setMapTool(self.prev_tool)
        self.fit_grid()

    def _area(self):
        """(extent, crs, description) of the chosen area, or a Grid for the 'same grid' modes."""
        mode = self.area_mode.currentData()
        canvas = self.iface.mapCanvas()
        if mode == "canvas":
            return canvas.extent(), canvas.mapSettings().destinationCrs(), "map canvas extent"
        if mode == "draw":
            if not self.drawn:
                raise ValueError("draw a rectangle on the map first")
            return self.drawn[0], self.drawn[1], "rectangle drawn on the map"
        if mode in ("layer", "selected", "raster"):
            layer = self.layer_combo.currentLayer()
            if layer is None:
                raise ValueError("choose a layer")
            if mode == "raster":
                return qgis_util.grid_from_raster(layer, _slug(self.name_edit.text())), None, \
                    f"grid of the raster {layer.source()}"
            if mode == "selected":
                if not isinstance(layer, QgsVectorLayer) or layer.selectedFeatureCount() == 0:
                    raise ValueError("select features of a vector layer first")
                return layer.boundingBoxOfSelected(), layer.crs(), \
                    f"bbox of {layer.selectedFeatureCount()} selected feature(s) of {layer.name()}"
            return layer.extent(), layer.crs(), f"extent of the layer {layer.name()}"
        if mode == "tiles":
            ids = [t for t in re.split(r"[\s,;]+", self.area_text_edit.text().strip()) if t]
            level = meshes.mesh(self.mesh_combo.currentData()).tile_level or "SM"
            for t in ids:
                if t not in meshes.existing_tiles(level):
                    raise ValueError(f"no {level} tile {t!r} in the BDC Grid V2")
            b = meshes.tiles_bbox(level, ids)
            return QgsRectangle(*b), qgis_util.albers_crs(), f"BDC {level} tiles {', '.join(ids)}"
        if mode == "lonlat":
            vals = [float(x) for x in re.split(r"[\s,;]+", self.area_text_edit.text().strip().strip("[]")) if x]
            if len(vals) != 4:
                raise ValueError("give four numbers: lon_min, lat_min, lon_max, lat_max")
            return QgsRectangle(*vals), qgis_util.wgs84(), f"lon/lat bbox {vals}"
        if mode == "toml":
            path = self.toml_widget.filePath()
            if not path:
                raise ValueError("choose a pipeline file")
            p = tomlio.load(path)
            if p.grid is None:
                raise ValueError(f"{path} has no [grid]")
            return p.grid, None, f"same [grid] as {os.path.basename(path)}"
        raise ValueError(mode)

    def fit_grid(self):
        try:
            area, crs, text = self._area()
            if isinstance(area, meshes.Grid):
                grid = area
                if self.area_mode.currentData() == "raster":
                    grid.name = _slug(self.name_edit.text())
                else:
                    self.name_edit.setText(grid.name)
            else:
                grid = qgis_util.fit_extent(_slug(self.name_edit.text()), area, crs, self._resolution(),
                                            self.mesh_combo.currentData(), self.to_tiles.isChecked())
        except (ValueError, OSError) as e:
            self.grid_report.setPlainText(f"error: {e}")
            return None
        self.name_edit.setText(grid.name)
        self.area_text = text
        grid.provenance = build.describe(grid, text)
        self.pipeline.grid = grid
        self.pipeline.header = []          # rewritten from the new grid at the next preview
        lines = checks.grid_report(grid)
        if grid.form == "geo":
            lines.append("written as a lon/lat [grid]: DisSCube projects and snaps it")
        self.grid_report.setPlainText("\n".join([f"area      : {text}"] + lines))
        return grid

    def show_grid(self):
        grid = self.pipeline.grid or self.fit_grid()
        if grid is None:
            return
        layer = qgis_util.grid_layer(grid)
        QgsProject.instance().addMapLayer(layer)
        level = meshes.mesh(grid.mesh).tile_level if grid.mesh in meshes.MESHES else None
        if level:
            ids = meshes.tiles_covering(level, grid.bbox_albers)
            if ids:
                tl = qgis_util.tiles_layer(level, ids)
                tl.renderer().symbol().setColor(QColor(0, 0, 0, 0))
                QgsProject.instance().addMapLayer(tl)
        if grid.cells > qgis_util.MAX_PREVIEW_CELLS:
            self.iface.messageBar().pushInfo("DisSCube", f"{grid.cells:,} cells: showing the outline only.")
        self.iface.mapCanvas().refresh()

    def show_all_tiles(self):
        level = meshes.mesh(self.mesh_combo.currentData()).tile_level or "SM"
        QgsProject.instance().addMapLayer(qgis_util.tiles_layer(level))

    # ── sources tab ─────────────────────────────────────────────────────────
    def _sources_tab(self):
        w = QWidget()
        v = QVBoxLayout(w)
        self.source_list = QListWidget()
        self.source_list.itemDoubleClicked.connect(lambda *_: self.edit_source())
        v.addWidget(self.source_list, 1)
        h = QHBoxLayout()
        self.source_type = QComboBox()
        self.source_type.addItems(catalog.source_types())
        self.source_type.setCurrentText("mapbiomas")
        h.addWidget(self.source_type)
        for text, slot in (("Add…", self.add_source), ("From layer", self.add_source_from_layer),
                           ("Edit…", self.edit_source), ("Remove", self.remove_source),
                           ("↑", lambda: self._move(self.pipeline.sources, self.source_list, -1)),
                           ("↓", lambda: self._move(self.pipeline.sources, self.source_list, 1))):
            b = QPushButton(text)
            b.clicked.connect(slot)
            h.addWidget(b)
        v.addLayout(h)
        self.source_layer = QgsMapLayerComboBox()
        self.source_layer.setFilters(compat.layer_filters("VectorLayer", "RasterLayer"))
        f = QFormLayout()
        f.addRow("Layer for 'From layer'", self.source_layer)
        v.addLayout(f)

        box = QGroupBox("Recipes (blocks that already ran in disscube-grids)")
        bl = QHBoxLayout(box)
        self.recipe_combo = QComboBox()
        for key, r in recipes.RECIPES.items():
            self.recipe_combo.addItem(r.label, key)
        self.recipe_combo.currentIndexChanged.connect(self._recipe_changed)
        self.recipe_arg = QLineEdit()
        b = QPushButton("Add")
        b.clicked.connect(self.add_recipe)
        bl.addWidget(self.recipe_combo, 2)
        bl.addWidget(self.recipe_arg, 1)
        bl.addWidget(b)
        v.addWidget(box)
        self._recipe_changed()
        return w

    def _recipe_changed(self):
        needs = recipes.RECIPES[self.recipe_combo.currentData()].needs
        self.recipe_arg.setEnabled(bool(needs))
        self.recipe_arg.setPlaceholderText({"years": "years, e.g. 2008, 2024",
                                            "period": "2020-07-01/2020-09-30"}.get(needs, ""))
        if needs == "period" and not self.recipe_arg.text().count("/"):
            self.recipe_arg.setText("2020-07-01/2020-09-30")
        elif needs == "years" and "/" in self.recipe_arg.text():
            self.recipe_arg.setText("")

    def add_recipe(self):
        key = self.recipe_combo.currentData()
        needs = recipes.RECIPES[key].needs
        kw = {}
        try:
            if needs == "years":
                kw["years"] = [int(x) for x in re.split(r"[\s,;]+", self.recipe_arg.text().strip()) if x]
                if not kw["years"]:
                    raise ValueError("give at least one year")
            elif needs == "period":
                kw["period"] = self.recipe_arg.text().strip()
            recipes.apply(self.pipeline, key, **kw)
        except ValueError as e:
            QMessageBox.warning(self, "Recipe", str(e))
            return
        self._refresh_lists()

    def add_source(self):
        d = SourceDialog(self.source_type.currentText(), {}, self)
        if d.exec():
            self.pipeline.sources.append(tomlio.Item(d.result_data))
            self._refresh_lists()

    def add_source_from_layer(self):
        layer = self.source_layer.currentLayer()
        if layer is None:
            QMessageBox.information(self, "Source", "Choose a layer.")
            return
        src = layer.source().split("|")[0]
        if not os.path.exists(src):
            QMessageBox.warning(self, "Source", f"{layer.name()} is not a local file ({src}).")
            return
        path = src
        if self.path:
            try:
                path = os.path.relpath(src, os.path.dirname(self.path)).replace(os.sep, "/")
            except ValueError:   # another drive on Windows
                path = src
        data = {"id": _slug(layer.name()), "type": "file", "path": path,
                "format": "raster" if isinstance(layer, QgsRasterLayer) else "vector"}
        if layer.crs().isValid() and layer.crs().authid():
            data["crs"] = layer.crs().authid()
        d = SourceDialog("file", data, self)
        if d.exec():
            item = tomlio.Item(d.result_data)
            if not self.path:
                item.comment.append("path is absolute: save the file and add the layer again for a relative path")
            self.pipeline.sources.append(item)
            self._refresh_lists()

    def edit_source(self):
        i = self.source_list.currentRow()
        if i < 0:
            return
        item = self.pipeline.sources[i]
        typ = item.get("type")
        if typ not in catalog.source_types():
            QMessageBox.warning(self, "Source", f"unknown type {typ!r}")
            return
        d = SourceDialog(typ, item.data, self)
        if d.exec():
            item.data = d.result_data
            self._refresh_lists()

    def remove_source(self):
        i = self.source_list.currentRow()
        if i >= 0:
            del self.pipeline.sources[i]
            self._refresh_lists()

    # ── derive tab ──────────────────────────────────────────────────────────
    def _derive_tab(self):
        w = QWidget()
        v = QVBoxLayout(w)
        self.derive_list = QListWidget()
        self.derive_list.itemDoubleClicked.connect(lambda *_: self.edit_derive())
        v.addWidget(self.derive_list, 1)
        h = QHBoxLayout()
        for text, slot in (("Add…", self.add_derive), ("Edit…", self.edit_derive), ("Remove", self.remove_derive),
                           ("↑", lambda: self._move(self.pipeline.derives, self.derive_list, -1)),
                           ("↓", lambda: self._move(self.pipeline.derives, self.derive_list, 1))):
            b = QPushButton(text)
            b.clicked.connect(slot)
            h.addWidget(b)
        v.addLayout(h)
        return w

    def add_derive(self):
        d = DeriveDialog({}, self.pipeline.source_ids(), self)
        if d.exec():
            self.pipeline.derives.append(tomlio.Item(d.result_data))
            self._refresh_lists()

    def edit_derive(self):
        i = self.derive_list.currentRow()
        if i < 0:
            return
        item = self.pipeline.derives[i]
        d = DeriveDialog(item.data, self.pipeline.source_ids(), self)
        if d.exec():
            item.data = d.result_data
            self._refresh_lists()

    def remove_derive(self):
        i = self.derive_list.currentRow()
        if i >= 0:
            del self.pipeline.derives[i]
            self._refresh_lists()

    def _move(self, items, widget, step):
        i = widget.currentRow()
        j = i + step
        if 0 <= i < len(items) and 0 <= j < len(items):
            items[i], items[j] = items[j], items[i]
            self._refresh_lists()
            widget.setCurrentRow(j)

    def _refresh_lists(self):
        self.source_list.clear()
        for s in self.pipeline.sources:
            years = s.get("years")
            self.source_list.addItem(f"{s.get('id')}  ({s.get('type')})" + (f"  years {years}" if years else ""))
        self.derive_list.clear()
        for d in self.pipeline.derives:
            extra = f" class {d.get('class_code')}" if d.get("class_code") is not None else ""
            extra += " + params" if d.get("params") else ""
            self.derive_list.addItem(f"{d.get('target')}  ←  {d.get('source')}   {d.get('operator')}{extra}")

    # ── file and run tab ────────────────────────────────────────────────────
    def _run_tab(self):
        w = QWidget()
        v = QVBoxLayout(w)
        self.preview = QPlainTextEdit()
        self.preview.setReadOnly(True)
        self.preview.setFont(_mono())
        v.addWidget(QLabel("The file as it will be saved"))
        v.addWidget(self.preview, 5)
        self.problems = QPlainTextEdit()
        self.problems.setReadOnly(True)
        self.problems.setMaximumHeight(64)
        v.addWidget(self.problems)

        box = QGroupBox("DisSCube (installed outside QGIS)")
        f = QFormLayout(box)
        self.py_widget = QgsFileWidget()
        # Qt's own dialog: it returns the path as chosen. The native one of a Flatpak QGIS goes through the
        # document portal and returns a copy under /run/user/…/doc/, with the venv's symlink resolved.
        self.py_widget.setOptions(QFileDialog.Option.DontUseNativeDialog)
        self.py_widget.lineEdit().setPlaceholderText("/home/<you>/venvs/disscube/bin/python")
        self.py_widget.setFilePath(disscube_cli.python())
        self.py_widget.fileChanged.connect(self._python_changed)
        prow = QHBoxLayout()
        prow.addWidget(self.py_widget, 1)
        b = QPushButton("Check")
        b.clicked.connect(self.check_disscube)
        prow.addWidget(b)
        f.addRow("Python with DisSCube", prow)
        if disscube_cli.in_flatpak():
            note = QLabel("QGIS runs as a Flatpak: DisSCube is started on the computer with flatpak-spawn. "
                          "Allow it once in a terminal, then restart QGIS:<br><code>"
                          f"{disscube_cli.FLATPAK_PERMISSION}</code>")
            note.setWordWrap(True)
            note.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            f.addRow("", note)
        self.workspace_edit = QLineEdit()
        self.workspace_edit.setPlaceholderText("data/<grid name>  (relative to the file)")
        f.addRow("Workspace", self.workspace_edit)
        self.output_edit = QLineEdit()
        self.output_edit.setPlaceholderText("data/<grid name>.tif  (relative to the file)")
        f.addRow("Output", self.output_edit)
        self.add_result = QCheckBox("Add the result to the map")
        self.add_result.setChecked(True)
        f.addRow("", self.add_result)
        v.addWidget(box)
        h = QHBoxLayout()
        self.validate_btn = QPushButton("Validate")
        self.validate_btn.clicked.connect(self.validate)
        self.run_btn = QPushButton("Run")
        self.run_btn.clicked.connect(self.run)
        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.clicked.connect(self.proc.cancel)
        self.cancel_btn.setEnabled(False)
        for b in (self.validate_btn, self.run_btn, self.cancel_btn):
            h.addWidget(b)
        v.addLayout(h)
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setFont(_mono())
        v.addWidget(self.log, 3)
        return w

    def _tab_changed(self, i):
        if self.tabs.widget(i) is self.tabs.widget(3):
            self.refresh_preview()

    def _sync_title(self):
        t = self.title_edit.text().strip()
        self.pipeline.name = t or self.pipeline.name

    def refresh_preview(self):
        self._sync_title()
        if not self.pipeline.header and self.pipeline.grid is not None:
            self.pipeline.header = build.new_pipeline(self.pipeline.grid, self.pipeline.name, self.area_text).header
        self.preview.setPlainText(tomlio.dumps(self.pipeline))
        probs = checks.check(self.pipeline)
        self.problems.setPlainText("\n".join(str(p) for p in probs) if probs else "No problems found by the plugin.")
        return probs

    # files
    def new_file(self):
        if not self._confirm_discard():
            return
        self.pipeline = tomlio.Pipeline()
        self.path = None
        self.title_edit.clear()
        self.file_label.setText("(not saved)")
        self.grid_report.clear()
        self._refresh_lists()
        self.refresh_preview()

    def _confirm_discard(self) -> bool:
        if not (self.pipeline.sources or self.pipeline.derives or self.pipeline.grid):
            return True
        return QMessageBox.question(self, "DisSCube", "Discard the current file?") == QMessageBox.StandardButton.Yes

    def open_file(self, path: str | None = None):
        if not path:
            path, _ = QFileDialog.getOpenFileName(self, "Open pipeline", self._dir(), "Pipeline (*.toml)",
                                                  options=QFileDialog.Option.DontUseNativeDialog)
        if not path:
            return
        try:
            p = tomlio.load(path)
        except Exception as e:  # noqa: BLE001 - show any parse error
            QMessageBox.warning(self, "Open", f"{path}:\n{e}")
            return
        self.pipeline = p
        self.path = path
        self.file_label.setText(path)
        self.title_edit.setText(p.name or "")
        if p.grid is not None:
            self.name_edit.setText(p.grid.name)
            self.grid_report.setPlainText("\n".join(checks.grid_report(p.grid)))
        self._refresh_lists()
        self.refresh_preview()
        if p.had_comments:
            self.iface.messageBar().pushMessage(
                "DisSCube", "This file has comments. Saving rewrites it without them: use 'Save as' to keep the "
                            "original.", Qgis.MessageLevel.Warning, 8)

    def _dir(self) -> str:
        return os.path.dirname(self.path) if self.path else str(Path.home())

    def save_file(self) -> bool:
        if not self.path:
            return self.save_file_as()
        if self.pipeline.had_comments:
            r = QMessageBox.question(self, "Save", "The file had comments; saving here removes them. Overwrite?",
                                     QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
                                     | QMessageBox.StandardButton.Save)
            if r == QMessageBox.StandardButton.Save:
                return self.save_file_as()
            if r != QMessageBox.StandardButton.Yes:
                return False
        return self._write(self.path)

    def save_file_as(self) -> bool:
        name = (self.pipeline.grid.name if self.pipeline.grid else "pipeline") + ".toml"
        # Qt's own dialog: in a Flatpak QGIS the native one returns a portal copy under /run/user/…/doc/, a folder
        # where DisSCube cannot write its data and QGIS cannot read the result back.
        path, _ = QFileDialog.getSaveFileName(self, "Save pipeline", os.path.join(self._dir(), name),
                                              "Pipeline (*.toml)", options=QFileDialog.Option.DontUseNativeDialog)
        if not path:
            return False
        if not path.endswith(".toml"):
            path += ".toml"
        return self._write(path)

    def _write(self, path: str) -> bool:
        if disscube_cli.is_portal_path(path):
            QMessageBox.warning(self, "Save", f"{path} is a copy made by the Flatpak file portal: DisSCube could not "
                                              "write its data next to it. Choose a folder of your own.")
            return False
        probs = self.refresh_preview()
        errs = [p for p in probs if p.level == "error"]
        if errs and QMessageBox.question(
                self, "Save", f"{len(errs)} problem(s) found (see the 'File and run' tab). Save anyway?") \
                != QMessageBox.StandardButton.Yes:
            return False
        name = os.path.basename(path)
        self.pipeline.header = [h.replace("<this file>", name) for h in self.pipeline.header]
        tomlio.dump(self.pipeline, path)
        self.path = path
        self.pipeline.had_comments = False
        self.file_label.setText(path)
        self.iface.messageBar().pushSuccess("DisSCube", f"saved {path}")
        return True

    # disscube
    def _python_changed(self, path):
        why = disscube_cli.check_python_path(path) if path else None
        if why:
            self._log(f"Python not saved: {why}")
            self.iface.messageBar().pushMessage("DisSCube", why, Qgis.MessageLevel.Warning, 12)
            return
        disscube_cli.set_python(path)

    def check_disscube(self):
        self._start(["--help"], code=disscube_cli.version_command(), then=self._version_done)

    def _version_done(self, code, out):
        v = out.strip().splitlines()[-1] if out.strip() else ""
        if code == 0:
            want = catalog.disscube_version()
            same = v.split(".")[:2] == want.split(".")[:2]
            self._log(f"DisSCube {v}" + ("" if same else f"  (the plugin knows {want}; the forms may miss fields)"))
        else:
            self._log("DisSCube not found in this Python")

    def _paths(self):
        base = os.path.dirname(self.path)
        g = self.pipeline.grid.name if self.pipeline.grid else "cube"
        ws = self.workspace_edit.text().strip() or f"data/{g}"
        out = self.output_edit.text().strip() or f"data/{g}.tif"
        return base, ws, out

    def _ready(self) -> bool:
        if self.proc.running():
            return False
        if not self.path or self.preview.toPlainText() != tomlio.dumps(self.pipeline):
            if not self.save_file():
                return False
        return True

    def validate(self):
        if self._ready():
            self._start(["validate", os.path.basename(self.path), "--json"], cwd=os.path.dirname(self.path),
                        then=self._validate_done)

    def _validate_done(self, code, out):
        j = disscube_cli.parse_json_tail(out)
        if j and j.get("status") == "ok":
            self.iface.messageBar().pushSuccess("DisSCube", "the file is valid for DisSCube")
        else:
            msg = (j or {}).get("error") or "see the log"
            self.iface.messageBar().pushMessage("DisSCube", f"invalid: {msg}", Qgis.MessageLevel.Warning, 10)

    def run(self):
        if not self._ready():
            return
        base, ws, out = self._paths()
        if not os.access(base, os.W_OK):
            msg = f"QGIS cannot write in {base}"
            if disscube_cli.in_flatpak():
                msg += (" (QGIS runs as a Flatpak). Save the file under your home folder, or run once: "
                        f"flatpak override --user --filesystem={base} org.qgis.qgis")
            self._log(msg)
            self.iface.messageBar().pushMessage("DisSCube", msg, Qgis.MessageLevel.Warning, 12)
            return
        self._start(["run", os.path.basename(self.path), "--workspace", ws, "--output", out, "-v"], cwd=base,
                    then=lambda c, o: self._run_done(c, base, ws, out))

    def _run_done(self, code, base, ws, out):
        if code != 0:
            self.iface.messageBar().pushMessage("DisSCube", f"run failed (exit {code}); see the log",
                                                Qgis.MessageLevel.Critical, 10)
            return
        rec = disscube_cli.run_record(os.path.join(base, ws))
        out_path = os.path.normpath(os.path.join(base, out))
        found = os.path.exists(out_path)
        if found:
            self._log(f"output    : {out_path}\nsha256    : {disscube_cli.sha256(out_path)}")
        if rec:
            self._log(f"run.json  : DisSCube {rec.get('disscube')}, grid {rec.get('grid')}, "
                      f"pipeline {rec.get('pipeline', {}).get('checksum', '')}")
        if not found:
            why = (f"DisSCube finished, but QGIS does not see {out_path}.")
            if disscube_cli.in_flatpak():
                why += (" QGIS runs as a Flatpak and may not have access to that folder: save the file under your home"
                        f" folder, or give access once in a terminal and restart QGIS:\n    "
                        f"flatpak override --user --filesystem={base} org.qgis.qgis")
            self._log(why)
            self.iface.messageBar().pushMessage("DisSCube", "run finished, but the output was not found; see the log",
                                                Qgis.MessageLevel.Warning, 12)
            return
        if self.add_result.isChecked():
            name = os.path.splitext(os.path.basename(out_path))[0]
            for old in QgsProject.instance().mapLayersByName(name):     # a new run replaces the layer of the last
                if os.path.normpath(old.source()) == out_path:
                    QgsProject.instance().removeMapLayer(old.id())
            layer = QgsRasterLayer(out_path, name)
            if layer.isValid():
                QgsProject.instance().addMapLayer(layer)
                self._log(f"added to the map: {name} ({layer.bandCount()} bands)")
            else:
                self._log(f"QGIS could not open {out_path}: {layer.error().summary()}")
        self.iface.messageBar().pushSuccess("DisSCube", "run finished")

    def _start(self, args, cwd=None, code=None, then=None):
        self._after = then
        try:
            kw = {"cwd": cwd}
            if code:
                kw["code"] = code
                args = []
            self.proc.start(args, **kw)
        except RuntimeError as e:
            self.iface.messageBar().pushMessage("DisSCube", str(e), Qgis.MessageLevel.Warning, 8)
            self._after = None
            return
        self._busy(True)

    def _busy(self, busy):
        self.validate_btn.setEnabled(not busy)
        self.run_btn.setEnabled(not busy)
        self.cancel_btn.setEnabled(busy)

    def _proc_done(self, code, out):
        self._busy(False)
        then, self._after = self._after, None
        if then:
            then(code, out)

    def _log(self, text):
        self.log.appendPlainText(text)

    def closeEvent(self, event):
        self.proc.cancel()
        super().closeEvent(event)
