"""Calls to a DisSCube installed outside QGIS.

DisSCube (rasterio, geopandas, zarr, …) is not installed in the Python of QGIS. The plugin runs it from the
Python of another environment — a virtual environment, conda, the ``.venv`` of a case — chosen in the plugin
settings, as ``python -c "from disscube.cli import main; …" <arguments>``. Everything goes through ``QProcess``,
so QGIS stays responsive and a run can be cancelled.
"""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

from qgis.PyQt.QtCore import QObject, QProcess, QProcessEnvironment, QSettings, pyqtSignal

SETTINGS_KEY = "disscube_qgis/python"
_MAIN = "import sys; from disscube.cli import main; sys.exit(main())"
_VERSION = "import importlib.metadata as m; print(m.version('disscube'))"


def configured_python() -> str:
    return str(QSettings().value(SETTINGS_KEY, "") or "")


def set_python(path: str) -> None:
    QSettings().setValue(SETTINGS_KEY, path)


def detect_python() -> str:
    """The Python next to a ``disscube`` command found on the PATH, or an empty string."""
    exe = shutil.which("disscube")
    if not exe:
        return ""
    folder = Path(exe).resolve().parent
    for name in ("python", "python3", "python.exe"):
        cand = folder / name
        if cand.exists():
            return str(cand)
    return ""


def python() -> str:
    return configured_python() or detect_python()


def sha256(path: str | Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


class DisscubeProcess(QObject):
    """One DisSCube command run in the background. Emits each output line and, at the end, the exit code."""

    line = pyqtSignal(str)
    done = pyqtSignal(int, str)   # exit code, all of stdout

    def __init__(self, parent=None):
        super().__init__(parent)
        self.proc: QProcess | None = None
        self._out: list[str] = []
        self._buf = ""

    def running(self) -> bool:
        return self.proc is not None and self.proc.state() != QProcess.NotRunning

    def start(self, args: list[str], cwd: str | None = None, interpreter: str | None = None,
              code: str = _MAIN) -> None:
        exe = interpreter or python()
        if not exe:
            raise RuntimeError("no Python with DisSCube configured (Settings of the DisSCube panel)")
        if self.running():
            raise RuntimeError("a DisSCube command is already running")
        self._out, self._buf = [], ""
        self.proc = QProcess(self)
        env = QProcessEnvironment.systemEnvironment()
        env.insert("PYTHONIOENCODING", "utf-8")
        env.insert("PYTHONUNBUFFERED", "1")
        # QGIS sets these for its own Python; they would point the other interpreter at the wrong libraries.
        for var in ("PYTHONHOME", "PYTHONPATH"):
            env.remove(var)
        self.proc.setProcessEnvironment(env)
        self.proc.setProcessChannelMode(QProcess.MergedChannels)
        if cwd:
            self.proc.setWorkingDirectory(cwd)
        self.proc.readyReadStandardOutput.connect(self._read)
        self.proc.finished.connect(self._finished)
        self.proc.errorOccurred.connect(self._error)
        shown = ["disscube", *args] if code == _MAIN else ["(version check)"]
        self.line.emit("$ " + " ".join([exe, *shown]))
        self.proc.start(exe, ["-c", code, *args])

    def cancel(self) -> None:
        if self.running():
            self.proc.kill()

    def _read(self) -> None:
        data = bytes(self.proc.readAllStandardOutput()).decode("utf-8", errors="replace")
        self._buf += data
        *lines, self._buf = self._buf.split("\n")
        for ln in lines:
            self._out.append(ln)
            self.line.emit(ln.rstrip("\r"))

    def _finished(self, code: int, _status) -> None:
        if self._buf:
            self._out.append(self._buf)
            self.line.emit(self._buf)
            self._buf = ""
        self.done.emit(int(code), "\n".join(self._out))

    def _error(self, err) -> None:
        if err == QProcess.FailedToStart:
            self.line.emit(f"could not start {self.proc.program()}: {self.proc.errorString()}")
            self.done.emit(-1, "")


def version_command() -> str:
    return _VERSION


def parse_json_tail(text: str) -> dict | None:
    """The JSON object printed by ``--json`` (the last ``{`` … ``}`` block of the output)."""
    start = text.find("{")
    while start != -1:
        try:
            return json.loads(text[start:])
        except json.JSONDecodeError:
            start = text.find("{", start + 1)
    return None


def run_record(workspace: str | Path) -> dict | None:
    p = Path(workspace) / "run.json"
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


__all__ = ["DisscubeProcess", "configured_python", "detect_python", "parse_json_tail", "python", "run_record",
           "set_python", "sha256", "version_command"]
