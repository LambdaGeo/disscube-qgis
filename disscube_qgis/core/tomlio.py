"""Read and write DisSCube pipeline files.

Reading uses ``tomllib`` (Python 3.11+) or the copy of ``tomli`` in ``_vendor`` (older Pythons that some QGIS
builds still ship). Writing is done here, by hand, in a fixed order — top-level keys, ``[grid]``, the sources,
the derived variables, ``[export]`` — so that the same pipeline always gives the same text and the comments the
plugin writes (where the grid came from, what a block is for) end up next to the blocks they describe.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

try:  # Python 3.11+
    import tomllib as _toml
except ModuleNotFoundError:  # pragma: no cover - older QGIS Pythons
    from ._vendor import tomli as _toml  # type: ignore[no-redef]

from . import meshes

TOP_ORDER = ["schema", "name", "workspace", "extent", "sources_from_catalog"]
GRID_ORDER = ["name", "crs", "resolution", "bbox", "snap"]
SOURCE_ORDER = ["id", "type", "name", "years"]
DERIVE_ORDER = ["target", "source", "operator", "class_code", "role", "years", "fill"]


@dataclass
class Item:
    """One [[source]] or [[derive]] block: its table and the comment lines written above it."""

    data: dict[str, Any]
    comment: list[str] = field(default_factory=list)

    def get(self, key: str, default: Any = None) -> Any:
        return self.data.get(key, default)


@dataclass
class Pipeline:
    name: str | None = None
    grid: meshes.Grid | None = None
    sources: list[Item] = field(default_factory=list)
    derives: list[Item] = field(default_factory=list)
    export: dict[str, Any] | str | None = None
    top: dict[str, Any] = field(default_factory=dict)        # workspace, extent, sources_from_catalog
    header: list[str] = field(default_factory=list)          # comment lines at the top of the file
    had_comments: bool = False                               # the file read had comments the writer will not keep

    def source_ids(self) -> list[str]:
        return [str(s.get("id")) for s in self.sources]


# ── reading ─────────────────────────────────────────────────────────────────

def loads(text: str) -> Pipeline:
    data = _toml.loads(text)
    return from_dict(data, had_comments=_has_comments(text))


def load(path: str | Path) -> Pipeline:
    return loads(Path(path).read_text(encoding="utf-8"))


def parse(text: str) -> dict[str, Any]:
    """The plain TOML dictionary (for comparisons)."""
    return _toml.loads(text)


def from_dict(data: dict[str, Any], had_comments: bool = False) -> Pipeline:
    data = dict(data)
    schema = data.pop("schema", None)
    if schema is not None and schema != 1:
        raise ValueError(f"pipeline schema {schema}; the plugin writes schema 1")
    p = Pipeline(had_comments=had_comments)
    p.name = data.pop("name", None)
    g = data.pop("grid", None)
    if g is not None:
        p.grid = meshes.from_table(g)
        extra = {k: v for k, v in g.items() if k not in GRID_ORDER}
        if extra:
            raise ValueError(f"[grid] has unknown keys {sorted(extra)}")
    p.sources = [Item(dict(s)) for s in data.pop("source", [])]
    p.derives = [Item(dict(d)) for d in data.pop("derive", [])]
    p.export = data.pop("export", None)
    p.top = data
    return p


def _has_comments(text: str) -> bool:
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("#"):
            return True
        if "#" in s and not _inside_string(s, s.index("#")):
            return True
    return False


def _inside_string(line: str, pos: int) -> bool:
    quote = None
    i = 0
    while i < pos:
        c = line[i]
        if quote:
            if c == "\\" and quote == '"':
                i += 2
                continue
            if c == quote:
                quote = None
        elif c in "\"'":
            quote = c
        i += 1
    return quote is not None


# ── writing ─────────────────────────────────────────────────────────────────

_BARE = re.compile(r"^[A-Za-z0-9_-]+$")


def _key(k: str) -> str:
    return k if _BARE.match(k) else _string(k)


def _string(s: str) -> str:
    out = ['"']
    for ch in s:
        if ch == '"':
            out.append('\\"')
        elif ch == "\\":
            out.append("\\\\")
        elif ch == "\n":
            out.append("\\n")
        elif ch == "\t":
            out.append("\\t")
        elif ord(ch) < 0x20 or ord(ch) == 0x7F:
            out.append(f"\\u{ord(ch):04x}")
        else:
            out.append(ch)
    out.append('"')
    return "".join(out)


def _float(v: float) -> str:
    if math.isnan(v):
        return "nan"
    if math.isinf(v):
        return "inf" if v > 0 else "-inf"
    r = repr(float(v))
    if "e" in r or "E" in r:
        mant, exp = r.lower().split("e")
        if "." not in mant:
            mant += ".0"
        return f"{mant}e{exp}"
    return r


def value(v: Any) -> str:
    """A TOML value (inline)."""
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, int):
        return str(v)
    if isinstance(v, float):
        return _float(v)
    if isinstance(v, str):
        return _string(v)
    if isinstance(v, (list, tuple)):
        return "[" + ", ".join(value(x) for x in v) + "]"
    if isinstance(v, dict):
        return "{" + ", ".join(f"{_key(str(k))} = {value(x)}" for k, x in v.items()) + "}"
    raise TypeError(f"cannot write {type(v).__name__} to TOML")


def _ordered(d: dict[str, Any], order: list[str]) -> list[str]:
    return [k for k in order if k in d] + [k for k in d if k not in order]


def _table(lines: list[str], path: str, d: dict[str, Any], order: list[str], header: str | None,
           notes: dict[str, str] | None = None) -> None:
    """Write the scalar keys of ``d``, then each nested table under ``[path.key]``.

    A nested table whose keys are all tables gets no header of its own (``[derive.params]`` with only
    ``[derive.params.groups]`` under it), since TOML defines it implicitly.
    """
    scalars = [k for k in _ordered(d, order) if d[k] is not None and not (isinstance(d[k], dict) and d[k])]
    nested = [k for k in _ordered(d, order) if isinstance(d[k], dict) and d[k]]
    if header is not None and (scalars or not nested or header.lstrip().startswith("[[")):
        lines.append(header)
    for k in scalars:
        line = f"{_key(str(k))} = {value(d[k])}"
        if notes and k in notes:
            line = f"{line}   # {notes[k]}"
        lines.append(line)
    for k in nested:
        sub = f"{path}.{_key(str(k))}"
        _table(lines, sub, d[k], [], f"\n[{sub}]")


def dumps(p: Pipeline) -> str:
    lines: list[str] = []
    for h in p.header:
        lines.append(f"# {h}".rstrip())
    if p.header:
        lines.append("")
    top = {"schema": 1}
    if p.name:
        top["name"] = p.name
    top.update(p.top)
    if isinstance(p.export, str):          # a top-level key: it must come before the first table
        top["export"] = p.export
    _table(lines, "", top, TOP_ORDER + ["export"], None)

    if p.grid is not None:
        lines.append("")
        for c in p.grid.provenance:
            lines.append(f"# {c}".rstrip())
        g = p.grid
        notes = {}
        if g.form == "geo":
            notes["bbox"] = "lon/lat (WGS84); DisSCube projects it to BDC Albers and snaps it"
            xmin, ymin, xmax, ymax = g.bbox_albers
            lines.append(f"# BDC Albers grid DisSCube builds from it: [{xmin:.1f}, {ymin:.1f}, {xmax:.1f}, {ymax:.1f}], "
                         f"{g.cols} x {g.rows} cells, id {g.grid_id!r}")
        else:
            notes["bbox"] = f"{g.cols} x {g.rows} cells"
        _table(lines, "grid", g.toml_table(), GRID_ORDER, "[grid]", notes)

    for s in p.sources:
        lines.append("")
        lines.extend(f"# {c}".rstrip() for c in s.comment)
        _table(lines, "source", s.data, SOURCE_ORDER, "[[source]]")

    for d in p.derives:
        lines.append("")
        lines.extend(f"# {c}".rstrip() for c in d.comment)
        _table(lines, "derive", d.data, DERIVE_ORDER, "[[derive]]")

    if isinstance(p.export, dict):
        lines.append("")
        _table(lines, "export", p.export, ["output", "format", "variables"], "[export]")
    return "\n".join(lines).rstrip() + "\n"


def dump(p: Pipeline, path: str | Path) -> None:
    Path(path).write_text(dumps(p), encoding="utf-8")
