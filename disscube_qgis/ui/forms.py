"""Dialogs that edit one [[source]] or [[derive]] block, built from the catalog of the pinned DisSCube.

Every field is a line where the value is typed as in TOML (``[2008, 2024]``, ``{forest = 1}``, ``1e-4``, ``true``)
or as plain text for a string. Fields with a fixed list of values are drop-downs. Required fields are in bold.
"""

from __future__ import annotations

from typing import Any

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from ..core import catalog, tomlio

_SOURCE_FIRST = ["id", "name", "years"]
_DERIVE_FIRST = ["target", "source", "operator", "class_code", "params", "years", "role", "fill"]


def _text(v: Any) -> str:
    if v is None:
        return ""
    if isinstance(v, str):
        return v
    return tomlio.value(v)


def parse_value(text: str, kinds: list[str]) -> Any:
    """A typed line as a TOML value; plain text is a string when the field takes strings."""
    text = text.strip()
    if text == "":
        return None
    try:
        return tomlio.parse(f"v = {text}")["v"]
    except Exception:
        if "str" in kinds:
            return text
        raise ValueError(f"not a TOML value: {text}") from None


class BlockDialog(QDialog):
    """Edit the fields of one block. ``fields`` comes from the catalog; ``data`` is the current table."""

    def __init__(self, title: str, doc: str, fields: dict[str, dict], data: dict[str, Any], first: list[str],
                 skip: tuple[str, ...] = (), parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.fields = fields
        self.widgets: dict[str, QWidget] = {}
        self.result_data: dict[str, Any] = {}
        self.extra = {k: v for k, v in data.items() if k not in fields}

        outer = QVBoxLayout(self)
        if doc:
            lab = QLabel(doc)
            lab.setWordWrap(True)
            outer.addWidget(lab)
        form_host = QWidget()
        self.form = QFormLayout(form_host)
        order = [k for k in first if k in fields] + sorted(k for k in fields if k not in first)
        for k in order:
            if k in skip:
                continue
            f = fields[k]
            w = self._widget(k, f, data.get(k))
            lab = QLabel(k)
            if f.get("required"):
                lab.setText(f"<b>{k}</b>")
            tip = f"{' or '.join(f['kinds'])}" + (f"; default {f['default']!r}" if f.get("default") is not None else "")
            lab.setToolTip(tip)
            w.setToolTip(tip)
            self.form.addRow(lab, w)
            self.widgets[k] = w
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(form_host)
        outer.addWidget(scroll)
        if self.extra:
            outer.addWidget(QLabel(f"Kept unchanged (not in the catalog): {', '.join(self.extra)}"))
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self._accept)
        bb.rejected.connect(self.reject)
        outer.addWidget(bb)
        self.resize(520, 520)

    def _widget(self, key: str, f: dict, v: Any) -> QWidget:
        if "enum" in f and len(f["enum"]) > 1:
            c = QComboBox()
            if not f.get("required"):
                c.addItem("")
            c.addItems([str(x) for x in f["enum"]])
            if v is not None:
                c.setCurrentText(str(v))
            return c
        if f["kinds"] == ["bool"]:
            c = QComboBox()
            c.addItems(["", "true", "false"])
            if v is not None:
                c.setCurrentText("true" if v else "false")
            return c
        e = QLineEdit(_text(v))
        if f.get("default") is not None:
            e.setPlaceholderText(_text(f["default"]))
        return e

    def value_of(self, key: str) -> Any:
        w = self.widgets[key]
        f = self.fields[key]
        if isinstance(w, QComboBox):
            t = w.currentText().strip()
            if t == "":
                return None
            if f["kinds"] == ["bool"]:
                return t == "true"
            return t
        return parse_value(w.text(), f["kinds"])

    def _accept(self) -> None:
        out: dict[str, Any] = {}
        try:
            for k in self.widgets:
                v = self.value_of(k)
                if v is not None:
                    out[k] = v
        except ValueError as e:
            QMessageBox.warning(self, self.windowTitle(), str(e))
            return
        out.update(self.extra)
        self.result_data = out
        self.accept()


class SourceDialog(BlockDialog):
    def __init__(self, typ: str, data: dict[str, Any] | None = None, parent=None):
        data = dict(data or {})
        data["type"] = typ
        super().__init__(f"Source: {typ}", catalog.source_doc(typ), catalog.source_fields(typ), data, _SOURCE_FIRST,
                         skip=("type",), parent=parent)
        self.typ = typ

    def _accept(self) -> None:
        super()._accept()
        if self.result():
            self.result_data = {"id": self.result_data.pop("id", ""), "type": self.typ, **self.result_data}


class DeriveDialog(BlockDialog):
    def __init__(self, data: dict[str, Any] | None, source_ids: list[str], parent=None):
        super().__init__("Variable", "One derived variable: the operator applied to a source on the grid.",
                         catalog.derive_fields(), dict(data or {}), _DERIVE_FIRST, parent=parent)
        # source: a drop-down of the sources of the file (still editable)
        src = QComboBox()
        src.setEditable(True)
        src.addItems(source_ids)
        src.setCurrentText(str((data or {}).get("source", source_ids[0] if source_ids else "")))
        self._swap("source", src)
        op = QComboBox()
        ops = catalog.operators()
        for name in catalog.operator_names():
            op.addItem(name)
            o = ops[name]
            tip = o["doc"] + ("\nneeds class_code" if o["requires_class_code"] else "") + (
                "\nreads by blocks" if o["block_safe"] else "")
            if o["params"]:
                tip += "\nparams: " + "; ".join(f"{k}: {v}" for k, v in o["params"].items())
            op.setItemData(op.count() - 1, tip, Qt.ToolTipRole)
        op.setCurrentText(str((data or {}).get("operator", "mean")))
        self._swap("operator", op)
        self.help = QPlainTextEdit()
        self.help.setReadOnly(True)
        self.help.setMaximumHeight(90)
        self.layout().insertWidget(self.layout().count() - 1, self.help)
        op.currentTextChanged.connect(self._show_help)
        self._show_help(op.currentText())

    def _swap(self, key: str, w: QWidget) -> None:
        old = self.widgets[key]
        row, _role = self.form.getWidgetPosition(old)
        taken = self.form.takeRow(row)          # keeps the label, detaches the old field
        label = taken.labelItem.widget()
        old.deleteLater()
        w.setToolTip(old.toolTip())
        self.form.insertRow(row, label, w)
        self.widgets[key] = w

    def _show_help(self, name: str) -> None:
        o = catalog.operators().get(name)
        if not o:
            self.help.setPlainText("")
            return
        lines = [f"{name}: {o['doc']}"]
        if o["requires_class_code"]:
            lines.append("needs class_code (a code or a list of codes)")
        if o["params"]:
            lines.append("params, e.g. {subcells = 64}:")
            lines += [f"  {k}: {v}" for k, v in o["params"].items()]
        else:
            lines.append("no params")
        self.help.setPlainText("\n".join(lines))

    def value_of(self, key: str) -> Any:
        w = self.widgets[key]
        if key in ("source", "operator") and isinstance(w, QComboBox):
            t = w.currentText().strip()
            return t or None
        return super().value_of(key)
