import subprocess
import sys

from conftest import ROOT, needs_disscube
from disscube_qgis.core import catalog


def test_catalog_loads():
    assert catalog.disscube_version() == "0.6.0"
    assert "mapbiomas" in catalog.source_types()
    assert catalog.operators()["percentage"]["requires_class_code"]


@needs_disscube
def test_catalog_matches_the_installed_disscube():
    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "build_catalog.py"), "--check"],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
