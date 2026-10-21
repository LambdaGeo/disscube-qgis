import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

FIXTURES = ROOT / "tests" / "fixtures"
CASES = sorted((FIXTURES / "disscube-grids").glob("*.toml"))


def has(module: str) -> bool:
    try:
        __import__(module)
        return True
    except ImportError:
        return False


needs_pyproj = pytest.mark.skipif(not has("pyproj"), reason="pyproj not installed")
needs_disscube = pytest.mark.skipif(not has("disscube"), reason="disscube not installed")
