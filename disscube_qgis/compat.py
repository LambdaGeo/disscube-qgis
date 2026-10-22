"""Names that differ between QGIS 3 (Qt 5, PyQt5) and QGIS 4 (Qt 6, PyQt6).

Qt enums are written in full everywhere in the plugin (``Qt.ItemDataRole.ToolTipRole``), which PyQt5 5.15 and
PyQt6 both accept. What is left here are the QGIS names that moved between versions: QGIS 4 dropped the old enum
names that QGIS 3.34 still needs, so each one is looked up in the new place first.
"""

from __future__ import annotations

from qgis.core import Qgis, QgsFeatureSink, QgsProcessing, QgsProcessingParameterNumber, QgsWkbTypes


def _first(*candidates):
    for owner, path in candidates:
        obj = owner
        try:
            for part in path.split("."):
                obj = getattr(obj, part)
            return obj
        except AttributeError:
            continue
    raise AttributeError(f"none of {[p for _, p in candidates]} exists in this QGIS")


#: Polygon layer, for Processing sources and sinks.
VECTOR_POLYGON = _first((Qgis, "ProcessingSourceType.VectorPolygon"), (QgsProcessing, "TypeVectorPolygon"))
#: Double for QgsProcessingParameterNumber.
NUMBER_DOUBLE = _first((Qgis, "ProcessingNumberParameterType.Double"),
                       (QgsProcessingParameterNumber, "Double"))
#: Polygon geometry type.
WKB_POLYGON = _first((Qgis, "WkbType.Polygon"), (QgsWkbTypes, "Polygon"))
#: Flag for QgsFeatureSink.addFeature.
FAST_INSERT = _first((QgsFeatureSink, "Flag.FastInsert"), (QgsFeatureSink, "FastInsert"))


def field_type(name: str):
    """Type of a QgsField: QMetaType.Type in QGIS 3.38+ and 4, QVariant.Type before."""
    from qgis.PyQt.QtCore import QMetaType

    if Qgis.QGIS_VERSION_INT >= 33800:
        return getattr(QMetaType.Type, {"Int": "Int", "Double": "Double", "String": "QString",
                                        "LongLong": "LongLong"}[name])
    from qgis.PyQt.QtCore import QVariant

    return getattr(QVariant, name)


def layer_filters(*names: str):
    """Layer filters for a QgsMapLayerComboBox: Qgis.LayerFilter (3.34+), else the proxy-model enum."""
    enum = getattr(Qgis, "LayerFilter", None)
    if enum is None:
        from qgis.core import QgsMapLayerProxyModel

        enum = QgsMapLayerProxyModel
    out = getattr(enum, names[0])
    for n in names[1:]:
        out = out | getattr(enum, n)
    return out
