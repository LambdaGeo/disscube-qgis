"""What the plugin knows about DisSCube pipeline files, read from ``data/disscube_catalog.json``.

The JSON is generated from DisSCube itself by ``scripts/build_catalog.py`` (the source types and their fields,
the fields of [grid], [[derive]] and [export], and the operators with their parameters).
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any


@lru_cache(maxsize=1)
def catalog() -> dict[str, Any]:
    path = Path(__file__).resolve().parent / "data" / "disscube_catalog.json"
    return json.loads(path.read_text(encoding="utf-8"))


def disscube_version() -> str:
    return str(catalog()["disscube_version"])


def source_types() -> list[str]:
    return sorted(catalog()["sources"])


def source_fields(typ: str) -> dict[str, dict]:
    try:
        return catalog()["sources"][typ]["fields"]
    except KeyError:
        raise ValueError(f"unknown source type {typ!r}; the types are {', '.join(source_types())}") from None


def source_doc(typ: str) -> str:
    return str(catalog()["sources"][typ]["doc"])


def operators() -> dict[str, dict]:
    return catalog()["operators"]


def operator_names() -> list[str]:
    return sorted(operators())


def derive_fields() -> dict[str, dict]:
    return catalog()["derive"]["fields"]


def export_fields() -> dict[str, dict]:
    return catalog()["export"]["fields"]


def top_fields() -> dict[str, dict]:
    return catalog()["top"]
