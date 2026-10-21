"""Ready-made source and variable blocks, taken from cases that already ran with DisSCube 0.6.0.

Each recipe adds one or more [[source]] blocks (unless a source with the same id is already in the file, in which
case its years are merged) and one or more [[derive]] blocks. The blocks are copies of the files of
``LambdaGeo/disscube-grids`` v1.1.0 (cases ``para``, ``br163``, ``ilha_maranhao``); the comment above each block
says which one.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from .tomlio import Item, Pipeline

#: MapBiomas Collection 11 leaf codes grouped into the level-1 classes (disscube-grids, cases/para/sources.toml).
#: Code 91 (2024) was placed in "non vegetated area" by assumption: check the legend CSV of the collection.
MAPBIOMAS_L1_GROUPS = {
    "1": [1, 3, 4, 5, 6, 49],
    "2": [10, 11, 12, 13, 29, 32, 50],
    "3": [9, 14, 15, 18, 19, 20, 21, 35, 36, 39, 40, 41, 46, 47, 48, 62],
    "4": [22, 23, 24, 25, 30, 75, 91],
    "5": [26, 31, 33],
}
MAPBIOMAS_L1_LABELS = {
    "1": "Forest", "2": "Herbaceous and shrubby vegetation", "3": "Farming", "4": "Non vegetated area", "5": "Water",
}


@dataclass(frozen=True)
class Recipe:
    key: str
    label: str
    needs: str          # what the user gives: "years", "period", "" (nothing)
    build: Callable[..., tuple[list[Item], list[Item]]]


def _mapbiomas_source(years: list[int]) -> Item:
    return Item({"id": "lulc_{year}", "type": "mapbiomas", "years": sorted(years), "collection": 11, "resolution": 30},
                ["MapBiomas land use, Collection 11 (30 m)"])


def _prodes_source(years: list[int]) -> Item:
    return Item({"id": "prodes_{year}", "type": "prodes", "years": sorted(years)},
                ["PRODES (Legal Amazon): situation at the end of each year; years are separable from 2007 on",
                 "Classes of the local map: 1 forest, 2 deforested up to the year, 3 other"])


def mapbiomas_landuse(years: list[int]) -> tuple[list[Item], list[Item]]:
    return [_mapbiomas_source(years)], [
        Item({"target": "landuse", "source": "lulc_{year}", "operator": "majority"},
             ["The MapBiomas class that covers most of the cell (as in disscube-grids, br163)"]),
    ]


def mapbiomas_level1(years: list[int]) -> tuple[list[Item], list[Item]]:
    labels = ", ".join(f"{k} {v}" for k, v in MAPBIOMAS_L1_LABELS.items())
    return [_mapbiomas_source(years)], [
        Item({"target": "l1_class", "source": "lulc_{year}", "operator": "majority",
              "params": {"groups": {k: list(v) for k, v in MAPBIOMAS_L1_GROUPS.items()}}},
             [f"MapBiomas level 1 through `groups` (as in disscube-grids, para): {labels}",
              "Code 91 placed in group 4 by assumption: check the legend CSV of Collection 11"]),
    ]


def mapbiomas_forest_pasture(years: list[int]) -> tuple[list[Item], list[Item]]:
    return [_mapbiomas_source(years)], [
        Item({"target": "forest_pct", "source": "lulc_{year}", "operator": "percentage", "class_code": 3},
             ["Share of the cell in forest formation (MapBiomas 3), as in disscube-grids, br163"]),
        Item({"target": "pasture_pct", "source": "lulc_{year}", "operator": "percentage", "class_code": 15},
             ["Share of the cell in pasture (MapBiomas 15)"]),
    ]


def prodes_shares(years: list[int]) -> tuple[list[Item], list[Item]]:
    return [_prodes_source(years)], [
        Item({"target": "prodes_deforested_pct", "source": "prodes_{year}", "operator": "percentage", "class_code": 2},
             ["Share of the cell deforested up to the year (as in disscube-grids, amazonia_legal)"]),
        Item({"target": "prodes_forest_pct", "source": "prodes_{year}", "operator": "percentage", "class_code": 1}),
    ]


def bdc_ndvi_landsat(period: str = "2020-07-01/2020-09-30") -> tuple[list[Item], list[Item]]:
    return [Item({"id": "ndvi", "type": "bdc", "collection": "LANDSAT-16D-1", "asset": "NDVI", "period": period,
                  "scale": 1e-4},
                 ["Brazil Data Cube, Landsat 16-day composites (30 m); indices stored as int16 x 10 000",
                  "Reads every scene of the period whole: use it on small areas (as in disscube-grids, br163)"])], [
        Item({"target": "ndvi_mean", "source": "ndvi", "operator": "mean"}),
    ]


def bdc_ndvi_modis(period: str = "2020-07-01/2020-09-30") -> tuple[list[Item], list[Item]]:
    return [Item({"id": "ndvi", "type": "bdc", "collection": "mod13q1-6.1", "asset": "NDVI", "period": period,
                  "scale": 1e-4},
                 ["Brazil Data Cube, MODIS MOD13Q1 16-day composites (231.66 m), as in disscube-grids, para"])], [
        Item({"target": "ndvi_mean", "source": "ndvi", "operator": "mean"}),
    ]


def seats_distance() -> tuple[list[Item], list[Item]]:
    return [Item({"id": "seats", "type": "file", "path": "zip://ana/GEOFT_CIDADE_2016.zip",
                  "url": "https://metadados.snirh.gov.br/geonetwork/srv/api/records/"
                         "8db5549f-2b94-40f0-b968-6f940bad68fa/attachments/GEOFT_CIDADE_2016.zip",
                  "sha256": "0311f4267c4ea871b3e928bf8821ba03380a58595ff3e4cc5e77cf315f16c16a"},
                 ["The 5,570 municipal seats of IBGE BC250 (2016), from the ANA metadata catalogue",
                  "(as in disscube-grids, para/seats.toml)"])], [
        Item({"target": "dist_seats", "source": "seats", "operator": "distance", "params": {"crs": "EPSG:5880"}},
             ["Distance to the nearest seat, measured in EPSG:5880 (metres)"]),
    ]


RECIPES: dict[str, Recipe] = {r.key: r for r in [
    Recipe("mapbiomas-landuse", "MapBiomas: dominant class", "years", mapbiomas_landuse),
    Recipe("mapbiomas-l1", "MapBiomas: dominant level-1 class", "years", mapbiomas_level1),
    Recipe("mapbiomas-forest-pasture", "MapBiomas: forest and pasture shares", "years", mapbiomas_forest_pasture),
    Recipe("prodes", "PRODES: deforested and forest shares", "years", prodes_shares),
    Recipe("bdc-ndvi-modis", "BDC: NDVI, MODIS (large areas)", "period", bdc_ndvi_modis),
    Recipe("bdc-ndvi-landsat", "BDC: NDVI, Landsat (small areas)", "period", bdc_ndvi_landsat),
    Recipe("seats-distance", "IBGE: distance to municipal seats", "", seats_distance),
]}


def apply(p: Pipeline, key: str, **kwargs) -> None:
    """Add a recipe's blocks to a pipeline, merging the years of a source that is already there."""
    sources, derives = RECIPES[key].build(**kwargs)
    by_id = {s.get("id"): s for s in p.sources}
    for s in sources:
        have = by_id.get(s.get("id"))
        if have is None:
            p.sources.append(s)
            by_id[s.get("id")] = s
        elif have.get("type") != s.get("type"):
            raise ValueError(f"the file already has a source {s.get('id')!r} of type {have.get('type')!r}")
        elif s.get("years"):
            have.data["years"] = sorted(set(have.get("years") or []) | set(s.get("years")))
    existing = {(d.get("target"), d.get("source")) for d in p.derives}
    for d in derives:
        if (d.get("target"), d.get("source")) not in existing:
            p.derives.append(d)
