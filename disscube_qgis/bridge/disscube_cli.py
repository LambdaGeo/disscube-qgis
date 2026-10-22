"""Calls to a DisSCube installed outside QGIS.

DisSCube (rasterio, geopandas, zarr, …) is not installed in the Python of QGIS. The plugin runs it from the
Python of another environment — a virtual environment, conda, the ``.venv`` of a case — chosen in the plugin
settings, as ``python -c "from disscube.cli import main; …" <arguments>``. Everything goes through ``QProcess``,
so QGIS stays responsive and a run can be cancelled.

QGIS from Flathub (``org.qgis.qgis``) runs in a sandbox: a program started from it runs inside the sandbox, with the
libraries of the Flatpak runtime, and cannot run the Python of the computer. There the plugin starts DisSCube with
``flatpak-spawn --host``, which needs one permission given once on the computer::

    flatpak override --user --talk-name=org.freedesktop.Flatpak org.qgis.qgis

The file dialogs of a Flatpak app also hand back copies under ``/run/user/<uid>/doc/…`` (the document portal), with
symbolic links resolved — a ``venv/bin/python`` becomes the system Python. The path of the Python is therefore typed,
not picked, and a portal path is refused with an explanation.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
from pathlib import Path

from qgis.PyQt.QtCore import QObject, QProcess, QProcessEnvironment, QSettings, pyqtSignal

SETTINGS_KEY = "disscube_qgis/python"
_MAIN = "import sys; from disscube.cli import main; sys.exit(main())"
_VERSION = "import importlib.metadata as m; print(m.version('disscube'))"

FLATPAK_PERMISSION = "flatpak override --user --talk-name=org.freedesktop.Flatpak org.qgis.qgis"
_PORTAL = re.compile(r"^/run/user/\d+/doc/[0-9a-f]+/")


def in_flatpak() -> bool:
    """True when QGIS runs as a Flatpak (Flathub's org.qgis.qgis)."""
    return bool(os.environ.get("FLATPAK_ID")) or os.path.exists("/.flatpak-info")


def is_portal_path(path: str) -> bool:
    """A copy handed back by the document portal of a Flatpak app, not the real file."""
    return bool(_PORTAL.match(path or ""))


def check_python_path(path: str) -> str | None:
    """Why a path cannot be the Python with DisSCube, or None."""
    if not path:
        return "no Python given"
    if is_portal_path(path):
        return ("this is a copy made by the Flatpak file dialog (and it resolves a venv's python to the system "
                "Python): type the real path instead, e.g. /home/<you>/venvs/disscube/bin/python")
    return None


def command(exe: str, code: str, args: list[str], cwd: str | None, flatpak: bool) -> tuple[str, list[str]]:
    """Program and arguments that run ``exe -c code args`` in ``cwd``, outside the sandbox when in a Flatpak."""
    if not flatpak:
        return exe, ["-c", code, *args]
    pre = ["--host", "--watch-bus", "--env=PYTHONIOENCODING=utf-8", "--env=PYTHONUNBUFFERED=1"]
    if cwd:
        pre.append(f"--directory={cwd}")
    return "flatpak-spawn", [*pre, exe, "-c", code, *args]


def configured_python() -> str:
    return str(QSettings().value(SETTINGS_KEY, "") or "")


def set_python(path: str) -> None:
    QSettings().setValue(SETTINGS_KEY, path)


def detect_python() -> str:
    """The Python next to a ``disscube`` command found on the PATH, or an empty string (always empty in a Flatpak)."""
    if in_flatpak():
        return ""
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
        self._flatpak = False

    def running(self) -> bool:
        return self.proc is not None and self.proc.state() != QProcess.ProcessState.NotRunning

    def start(self, args: list[str], cwd: str | None = None, interpreter: str | None = None,
              code: str = _MAIN) -> None:
        exe = interpreter or python()
        if not exe:
            raise RuntimeError("no Python with DisSCube configured (Settings of the DisSCube panel)")
        if self.running():
            raise RuntimeError("a DisSCube command is already running")
        why = check_python_path(exe)
        if why:
            raise RuntimeError(why)
        flatpak = in_flatpak()
        self._flatpak = flatpak
        self._out, self._buf = [], ""
        self.proc = QProcess(self)
        env = QProcessEnvironment.systemEnvironment()
        env.insert("PYTHONIOENCODING", "utf-8")
        env.insert("PYTHONUNBUFFERED", "1")
        # QGIS sets these for its own Python; they would point the other interpreter at the wrong libraries.
        for var in ("PYTHONHOME", "PYTHONPATH"):
            env.remove(var)
        self.proc.setProcessEnvironment(env)
        self.proc.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        if cwd and not flatpak:
            self.proc.setWorkingDirectory(cwd)
        self.proc.readyReadStandardOutput.connect(self._read)
        self.proc.finished.connect(self._finished)
        self.proc.errorOccurred.connect(self._error)
        shown = ["disscube", *args] if code == _MAIN else ["(version check)"]
        self.line.emit("$ " + ("flatpak-spawn --host " if flatpak else "") + " ".join([exe, *shown]))
        program, arguments = command(exe, code, args, cwd, flatpak)
        self.proc.start(program, arguments)

    def cancel(self) -> None:
        if self.running():
            # flatpak-spawn passes SIGTERM on to the program on the host; SIGKILL would only stop flatpak-spawn
            self.proc.terminate()
            if not self.proc.waitForFinished(5000):
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
        text = "\n".join(self._out)
        if getattr(self, "_flatpak", False) and code != 0 and (
                "org.freedesktop.Flatpak" in text or "Portal call failed" in text or "not allowed" in text):
            self.line.emit("QGIS runs as a Flatpak and may not start programs on the computer yet. "
                           f"Run once in a terminal, then restart QGIS:\n    {FLATPAK_PERMISSION}")
        self.done.emit(int(code), "\n".join(self._out))

    def _error(self, err) -> None:
        if err == QProcess.ProcessError.FailedToStart:
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


__all__ = ["DisscubeProcess", "FLATPAK_PERMISSION", "check_python_path", "command", "configured_python",
           "detect_python", "in_flatpak", "is_portal_path", "parse_json_tail", "python", "run_record", "set_python",
           "sha256", "version_command"]
