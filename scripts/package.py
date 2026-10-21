#!/usr/bin/env python
"""Build dist/disscube_qgis-<version>.zip, the archive QGIS installs ("Install from ZIP") or the plugin repository takes.

    python scripts/package.py
"""
from __future__ import annotations

import configparser
import pathlib
import zipfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
PKG = ROOT / "disscube_qgis"
SKIP_DIRS = {"__pycache__"}
SKIP_SUFFIX = {".pyc", ".pyo"}


def main() -> None:
    meta = configparser.ConfigParser()
    meta.read(PKG / "metadata.txt", encoding="utf-8")
    version = meta["general"]["version"]
    out = ROOT / "dist" / f"disscube_qgis-{version}.zip"
    out.parent.mkdir(exist_ok=True)
    n = 0
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for f in sorted(PKG.rglob("*")):
            if f.is_dir() or SKIP_DIRS & set(f.parts) or f.suffix in SKIP_SUFFIX:
                continue
            z.write(f, f.relative_to(ROOT).as_posix())
            n += 1
    print(f"{out} ({n} files)")


if __name__ == "__main__":
    main()
