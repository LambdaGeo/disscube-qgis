import pytest

from conftest import CASES
from disscube_qgis.core import checks, meshes, tomlio


@pytest.mark.parametrize("case", CASES, ids=lambda c: c.name)
def test_cases_have_no_errors(case):
    assert checks.errors(tomlio.load(case)) == []


def _p(text):
    return tomlio.loads('schema = 1\n[grid]\nname = "g"\nbbox = [-50, -5, -49, -4]\nresolution = 1000\n' + text)


@pytest.mark.parametrize("text, message", [
    ('[[source]]\nid = "a"\ntype = "nope"\n', "unknown type"),
    ('[[source]]\nid = "lulc"\ntype = "mapbiomas"\nyear = 2024\ncolection = 11\n', "unknown field 'colection'"),
    ('[[source]]\nid = "p_{year}"\ntype = "prodes"\nyears = [2005]\n', "from 2007 on"),
    ('[[source]]\nid = "m"\ntype = "mapbiomas"\nyear = 1970\n', "covers 1985"),
    ('[[source]]\nid = "m"\ntype = "mapbiomas"\nyears = [2020]\n', "requires '{year}'"),
    ('[[source]]\nid = "n"\ntype = "bdc"\ncollection = "X"\nperiod = "2020"\n', "exactly one of 'asset'"),
    ('[[source]]\nid = "m"\ntype = "mapbiomas"\nyear = 2020\n[[derive]]\ntarget = "t"\nsource = "mm"\noperator = "mean"\n',
     "unknown source 'mm'"),
    ('[[source]]\nid = "m"\ntype = "mapbiomas"\nyear = 2020\n[[derive]]\ntarget = "t"\nsource = "m"\noperator = "percentage"\n',
     "needs class_code"),
    ('[[source]]\nid = "m"\ntype = "mapbiomas"\nyear = 2020\n[[derive]]\ntarget = "t"\nsource = "m"\noperator = "avg"\n',
     "unknown operator"),
    ('[[source]]\nid = "m"\ntype = "mapbiomas"\nyear = 2020\n[[derive]]\ntarget = "t"\nsource = "m"\noperator = "mean"\n'
     '[derive.params]\nsubcels = 4\n', "has no parameter 'subcels'"),
    ('[[source]]\nid = "m_{year}"\ntype = "mapbiomas"\nyears = [2020]\n[[source]]\nid = "m_2020"\ntype = "mapbiomas"\n'
     'year = 2020\n', "duplicate source ids"),
])
def test_errors(text, message):
    errs = [str(e) for e in checks.errors(_p(text))]
    assert any(message in e for e in errs), errs


def test_grid_report_mentions_tiles_and_meshes():
    g = meshes.fit_albers("g", (4.5e6, 1.02e7, 4.6e6, 1.03e7), 5280.0, "bdc-sm", to_tiles=True)
    text = "\n".join(checks.grid_report(g))
    assert "4 SM" in text and "bdc-sm" in text and "MapBiomas" in text
