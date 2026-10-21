"""Entry point of the DisSCube plugin: menu, toolbar button, panel and Processing provider."""

from __future__ import annotations

import os

from qgis.core import QgsApplication
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import QAction

from .processing_provider.provider import DisSCubeProvider
from .ui.dock import DisSCubeDock

MENU = "&DisSCube"


class DisSCubePlugin:
    def __init__(self, iface):
        self.iface = iface
        self.plugin_dir = os.path.dirname(__file__)
        self.dock = None
        self.action = None
        self.provider = None

    def initProcessing(self):
        provider = DisSCubeProvider()
        # addProvider refuses (and deletes) a provider whose id is already registered
        self.provider = provider if QgsApplication.processingRegistry().addProvider(provider) else None

    def initGui(self):
        self.initProcessing()
        icon = QIcon(os.path.join(self.plugin_dir, "icon.png"))
        self.action = QAction(icon, "DisSCube grids and pipelines", self.iface.mainWindow())
        self.action.setCheckable(True)
        self.action.triggered.connect(self.toggle)
        self.iface.addPluginToRasterMenu(MENU, self.action)
        self.iface.addRasterToolBarIcon(self.action)

    def _ensure_dock(self):
        if self.dock is None:
            self.dock = DisSCubeDock(self.iface, self.iface.mainWindow())
            self.iface.addDockWidget(Qt.RightDockWidgetArea, self.dock)
            self.dock.visibilityChanged.connect(self.action.setChecked)
        return self.dock

    def toggle(self, checked=None):
        dock = self._ensure_dock()
        show = not dock.isVisible() if checked is None else bool(checked)
        dock.setVisible(show)
        if show:
            dock.raise_()

    def unload(self):
        if self.action is not None:
            self.iface.removePluginRasterMenu(MENU, self.action)
            self.iface.removeRasterToolBarIcon(self.action)
            self.action.deleteLater()
            self.action = None
        if self.dock is not None:
            self.dock.proc.cancel()
            self.iface.removeDockWidget(self.dock)
            self.dock.deleteLater()
            self.dock = None
        if self.provider is not None:
            QgsApplication.processingRegistry().removeProvider(self.provider)
            self.provider = None
