#!/usr/bin/env python
"""Write disscube_qgis/core/data/bdc_tiles.json: the ids of the BDC Grid V2 tiles (SM, MD, LG).

The tile geometry follows a closed formula (see disscube_qgis/core/meshes.py); only the list of tiles that
exist is data. The ids are read from the shapefiles bundled with DisSCube (disscube/data/bdc_grids/*.zip),
and the script checks that every tile matches the formula.

    pip install disscube==0.6.0 pyshp
    python scripts/build_bdc_tiles.py
"""
from __future__ import annotations

import hashlib
import io
import json
import pathlib
import sys
import zipfile
from importlib.resources import files

import shapefile  # pyshp

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from disscube_qgis.core.meshes import TILE_LEVELS, tile_bounds  # noqa: E402

OUT = ROOT / "disscube_qgis" / "core" / "data" / "bdc_tiles.json"


def main() -> None:
    from importlib.metadata import version

    out: dict = {"source": f"disscube {version('disscube')}, disscube/data/bdc_grids/BDC_<level>_V2.zip", "levels": {}}
    for level in TILE_LEVELS:
        path = files("disscube") / "data" / "bdc_grids" / f"BDC_{level}_V2.zip"
        raw = path.read_bytes()
        with zipfile.ZipFile(io.BytesIO(raw)) as z:
            stem = next(n[:-4] for n in z.namelist() if n.endswith(".shp"))
            r = shapefile.Reader(shp=io.BytesIO(z.read(stem + ".shp")), shx=io.BytesIO(z.read(stem + ".shx")),
                                 dbf=io.BytesIO(z.read(stem + ".dbf")))
            ids = []
            for sr in r.iterShapeRecords():
                tid = sr.record[0]
                b = sr.shape.bbox
                want = tile_bounds(level, tid)
                if any(abs(a - w) > 1e-6 for a, w in zip(b, want)):
                    raise SystemExit(f"tile {level} {tid}: {b} does not follow the formula {want}")
                ids.append(tid)
        out["levels"][level] = {"sha256": hashlib.sha256(raw).hexdigest(), "tiles": sorted(ids)}
        print(f"{level}: {len(ids)} tiles, all on the formula")
    OUT.write_text(json.dumps(out, indent=1) + "\n", encoding="utf-8")
    print(OUT)


if __name__ == "__main__":
    main()
