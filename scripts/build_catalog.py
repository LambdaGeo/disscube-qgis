#!/usr/bin/env python
"""Write disscube_qgis/core/data/disscube_catalog.json from an installed DisSCube.

The plugin does not import DisSCube (it is not installed in the Python of QGIS). What the plugin needs to know
about pipeline files — the fields of each source type, of [grid], [[derive]] and [export], and the operators with
their parameters — is read here from the DisSCube the plugin is pinned to, and stored as data. The test
``tests/test_catalog.py`` regenerates it and fails if it differs, so a new DisSCube that adds a field or an
operator is noticed.

    pip install disscube==0.6.0
    python scripts/build_catalog.py            # writes the file
    python scripts/build_catalog.py --check    # exit 1 if the file is out of date
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT = ROOT / "disscube_qgis" / "core" / "data" / "disscube_catalog.json"


def _kind(prop: dict) -> dict:
    """A compact description of a JSON-schema property: kind, enum, default, required later."""
    opts = prop.get("anyOf") or [prop]
    kinds = []
    enum = None
    for o in opts:
        t = o.get("type")
        if t == "null":
            continue
        if "const" in o:
            enum = [o["const"]]
            kinds.append("str")
        elif "enum" in o:
            enum = list(o["enum"])
            kinds.append("str")
        elif t == "array":
            item = o.get("items", {})
            it = item.get("type", "any")
            kinds.append(f"list[{it}]")
        elif t == "object":
            kinds.append("table")
        elif t in ("string", "integer", "number", "boolean"):
            kinds.append({"string": "str", "integer": "int", "number": "float", "boolean": "bool"}[t])
        elif "$ref" in o:
            kinds.append("table")
        else:
            kinds.append("any")
    out: dict = {"kinds": kinds}
    if enum is not None:
        out["enum"] = enum
    if "default" in prop:
        out["default"] = prop["default"]
    if "minItems" in prop or any("minItems" in o for o in opts):
        mins = [o.get("minItems") for o in opts if "minItems" in o] or [prop.get("minItems")]
        out["min_items"] = mins[0]
    return out


def _fields(defn: dict) -> dict:
    req = set(defn.get("required", []))
    fields = {}
    for name, prop in defn.get("properties", {}).items():
        f = _kind(prop)
        f["required"] = name in req
        fields[name] = f
    return {"doc": (defn.get("description") or "").strip().split("\n\n")[0], "fields": fields}


def build() -> dict:
    from importlib.metadata import version

    import disscube.operators.proximity  # noqa: F401  (registers the operators)
    import disscube.operators.zonal  # noqa: F401
    from disscube.operators.base import OPERATOR_REGISTRY
    from disscube.pipeline.schema import PipelineConfig

    schema = PipelineConfig.model_json_schema(by_alias=True)
    defs = schema["$defs"]
    mapping = schema["properties"]["source"]["items"]["discriminator"]["mapping"]
    sources = {}
    for typ, ref in sorted(mapping.items()):
        sources[typ] = _fields(defs[ref.split("/")[-1]])
    operators = {}
    for name, cls in sorted(OPERATOR_REGISTRY.items()):
        doc = (cls.__doc__ or "").strip().split("\n\n")[0]
        operators[name] = {
            "doc": " ".join(doc.split()),
            "requires_class_code": bool(cls.requires_class_code),
            "block_safe": bool(cls.block_safe),
            "clip_to_grid": bool(cls.clip_to_grid),
            "params": dict(cls.params),
        }
    from disscube.sources import mapbiomas

    mb = [{"collection": c, "resolution": r, "first_year": d.first_year, "last_year": d.last_year}
          for (c, r), d in sorted(mapbiomas.DATASETS.items())]
    top = {k: _kind(v) for k, v in schema["properties"].items() if k not in ("source", "derive", "grid", "export")}
    return {
        "disscube_version": version("disscube"),
        "schema": 1,
        "top": top,
        "grid": _fields(defs["GridConfig"]),
        "derive": _fields(defs["DeriveConfig"]),
        "export": _fields(defs["ExportConfig"]),
        "sources": sources,
        "operators": operators,
        "mapbiomas": {"datasets": mb, "classes": {str(k): v for k, v in sorted(mapbiomas.CLASSES.items())},
                      "legend_url": mapbiomas.LEGEND_URL},
        "prodes": {"first_separable_year": 2007},
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args()
    text = json.dumps(build(), indent=1, ensure_ascii=False, sort_keys=True) + "\n"
    if a.check:
        if not OUT.exists() or OUT.read_text(encoding="utf-8") != text:
            print(f"{OUT} is out of date for the installed DisSCube; run scripts/build_catalog.py", file=sys.stderr)
            return 1
        print("catalog up to date")
        return 0
    OUT.write_text(text, encoding="utf-8")
    print(OUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
