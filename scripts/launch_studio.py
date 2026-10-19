"""One-click launcher for Alien Time Listing Studio (used by start-studio.bat and start-studio.sh).

Standard library only, because it runs before anything is installed. It:
  1. creates the private Python environment (.venv) on first run,
  2. installs or updates the Python packages when requirements change,
  3. creates .env from .env.example if it is missing (secrets stay empty),
  4. makes sure the web interface is built (rebuilds it when Node.js is available and the source changed),
  5. starts the studio (backend + built-in web interface) on this computer only,
  6. opens it in your browser and keeps running until you close the window or press Ctrl+C.

Usage:  python scripts/launch_studio.py [dev] [--port 8000] [--no-browser] [--reinstall] [--rebuild]
  dev           developer mode: live-reloading backend + Vite frontend dev server (needs Node.js)
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import time
import urllib.request
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FRONTEND = ROOT / "frontend"
WEB_INDEX = ROOT / "app" / "web" / "index.html"
VENV = ROOT / ".venv"
IS_WINDOWS = os.name == "nt"
VENV_PY = VENV / ("Scripts/python.exe" if IS_WINDOWS else "bin/python")
REQUIREMENT_FILES = [ROOT / "requirements.txt", ROOT / "requirements-integrations.txt"]
HOST = "127.0.0.1"  # this computer only; see docs/DEPLOYMENT.md for safe remote access
MIN_PYTHON = (3, 12)


def say(msg: str = "") -> None:
    print(f"[studio] {msg}" if msg else "", flush=True)


def fail(msg: str, code: int = 1) -> None:
    say("")
    say("PROBLEM: " + msg)
    sys.exit(code)


def run(cmd: list[str], cwd: Path | None = None, env: dict | None = None) -> int:
    return subprocess.call(cmd, cwd=str(cwd or ROOT), env=env)


# ---- Python environment ---------------------------------------------------------------------------
def python_version(py: Path) -> tuple[int, int] | None:
    try:
        out = subprocess.check_output([str(py), "-c", "import sys; print(sys.version_info[0], sys.version_info[1])"],
                                      text=True, stderr=subprocess.DEVNULL, timeout=60)
        major, minor = out.split()
        return int(major), int(minor)
    except Exception:  # noqa: BLE001
        return None


def ensure_venv() -> None:
    if VENV_PY.exists():
        ver = python_version(VENV_PY)
        if ver and ver >= MIN_PYTHON:
            return
        old = VENV.with_name(f".venv-old-{time.strftime('%Y%m%d-%H%M%S')}")
        say(f"The existing .venv uses an unsupported Python ({ver}); moving it aside to {old.name}.")
        VENV.rename(old)
    say("First run: creating the private Python environment (.venv) ...")
    if run([sys.executable, "-m", "venv", str(VENV)]) != 0 or not VENV_PY.exists():
        fail("Could not create the Python environment. On Linux install the venv package "
             "(e.g. sudo apt install python3.12-venv) and try again.")


def requirements_digest() -> str:
    h = hashlib.sha256()
    for f in REQUIREMENT_FILES:
        if f.exists():
            h.update(f.read_bytes())
    h.update(f"{VENV_PY}".encode())
    return h.hexdigest()


def ensure_packages(force: bool) -> None:
    marker = VENV / ".studio-packages.sha256"
    want = requirements_digest()
    if not force and marker.exists() and marker.read_text().strip() == want:
        return
    say("Installing Python packages. The first time this downloads about 500 MB and takes a few minutes ...")
    run([str(VENV_PY), "-m", "pip", "install", "--disable-pip-version-check", "--upgrade", "pip"])
    cmd = [str(VENV_PY), "-m", "pip", "install", "--disable-pip-version-check"]
    for f in REQUIREMENT_FILES:
        if f.exists():
            cmd += ["-r", str(f)]
    if run(cmd) != 0:
        fail("Installing the Python packages failed (see the messages above). Check your internet connection "
             "and run the launcher again; it continues where it stopped.")
    marker.write_text(want)
    say("Python packages are ready.")


# ---- configuration -------------------------------------------------------------------------------
def read_env_file() -> dict[str, str]:
    values: dict[str, str] = {}
    env_file = ROOT / ".env"
    if not env_file.exists():
        return values
    for line in env_file.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def ensure_env_file() -> dict[str, str]:
    env_file = ROOT / ".env"
    if not env_file.exists():
        shutil.copyfile(ROOT / ".env.example", env_file)
        say("Created .env from .env.example (all secrets empty).")
    values = read_env_file()
    if not values.get("OPENAI_API_KEY") and values.get("AI_PROVIDER", "auto") not in ("mock",):
        say("Note: OPENAI_API_KEY is empty in .env, so AI features show as 'not configured'.")
        say("      Add your key to .env and restart to switch them on. Everything else works without it.")
    return values


# ---- web interface -------------------------------------------------------------------------------
def newest_source_mtime() -> float:
    newest = 0.0
    for p in [FRONTEND / "index.html", FRONTEND / "package.json", FRONTEND / "vite.config.ts"]:
        if p.exists():
            newest = max(newest, p.stat().st_mtime)
    for folder in (FRONTEND / "src", FRONTEND / "public"):
        if folder.exists():
            for p in folder.rglob("*"):
                if p.is_file():
                    newest = max(newest, p.stat().st_mtime)
    return newest


def npm_path() -> str | None:
    return shutil.which("npm.cmd" if IS_WINDOWS else "npm") or shutil.which("npm")


def ensure_node_modules(npm: str) -> None:
    lock = FRONTEND / "package-lock.json"
    installed = FRONTEND / "node_modules" / ".package-lock.json"
    if installed.exists() and (not lock.exists() or installed.stat().st_mtime >= lock.stat().st_mtime):
        return
    say("Installing the web interface's build tools (npm install) ...")
    if run([npm, "install", "--no-audit", "--no-fund"], cwd=FRONTEND) != 0:
        fail("npm install failed (see above).")


def ensure_web_build(force: bool, dev: bool) -> None:
    npm = npm_path()
    if dev:
        if not npm:
            fail("Developer mode needs Node.js (https://nodejs.org). Start without 'dev' to use the built interface.")
        ensure_node_modules(npm)
        return
    built = WEB_INDEX.exists()
    stale = built and FRONTEND.exists() and newest_source_mtime() > WEB_INDEX.stat().st_mtime + 2
    if built and not stale and not force:
        return
    if not npm:
        if built:
            say("The web interface source is newer than the built copy, but Node.js is not installed;")
            say("using the built copy. Install Node.js to rebuild it automatically.")
            return
        fail("The built web interface (app/web) is missing and Node.js is not installed to build it. "
             "Install Node.js from https://nodejs.org or restore the app/web folder.")
    ensure_node_modules(npm)
    say("Building the web interface ...")
    if run([npm, "run", "build"], cwd=FRONTEND) != 0:
        if built:
            say("Rebuilding failed; starting with the previous build.")
            return
        fail("Building the web interface failed (see above).")


# ---- server --------------------------------------------------------------------------------------
def health(port: int, timeout: float = 1.5) -> bool:
    try:
        with urllib.request.urlopen(f"http://{HOST}:{port}/api/health", timeout=timeout) as r:
            return json.loads(r.read().decode() or "{}").get("status") == "ok"
    except Exception:  # noqa: BLE001
        return False


def port_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        return s.connect_ex((HOST, port)) != 0


def choose_port(preferred: int) -> tuple[int, bool]:
    """(port, already_running)."""
    if health(preferred):
        return preferred, True
    for port in range(preferred, preferred + 20):
        if port_free(port):
            if port != preferred:
                say(f"Port {preferred} is used by another program; using {port} instead.")
            return port, False
    fail(f"No free port between {preferred} and {preferred + 19}.")
    raise SystemExit  # unreachable


def spawn(cmd: list[str], cwd: Path, env: dict) -> subprocess.Popen:
    # On macOS/Linux each server gets its own process group, so stopping it also stops anything it started
    # (uvicorn's reloader, npm -> vite -> node). On Windows Ctrl+C reaches every process in the window.
    return subprocess.Popen(cmd, cwd=str(cwd), env=env, start_new_session=not IS_WINDOWS)


def stop(proc: subprocess.Popen | None) -> None:
    if proc is None:
        return
    if IS_WINDOWS:
        if proc.poll() is None:
            try:
                proc.wait(timeout=5)  # Ctrl+C in the window reaches the servers too; let them finish cleanly
            except subprocess.TimeoutExpired:
                pass
        subprocess.call(["taskkill", "/T", "/F", "/PID", str(proc.pid)], stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL)
        return
    for sig, grace in ((signal.SIGINT, 10), (signal.SIGTERM, 5), (signal.SIGKILL, 2)):
        try:
            os.killpg(proc.pid, sig)
        except (ProcessLookupError, PermissionError):
            return  # nothing left in the group
        try:
            proc.wait(timeout=grace)
        except subprocess.TimeoutExpired:
            continue
        try:  # leader exited; make sure nothing it started is left behind
            os.killpg(proc.pid, signal.SIGTERM)
        except (ProcessLookupError, PermissionError):
            pass
        return


def _stop_on_signals() -> None:
    """Treat 'window closed' / 'please stop' signals like Ctrl+C so both servers are shut down cleanly."""
    def handler(signum, frame):  # noqa: ARG001
        raise KeyboardInterrupt

    names = ["SIGTERM", "SIGHUP", "SIGBREAK"]
    if signal.getsignal(signal.SIGINT) is signal.SIG_IGN:  # started in the background: still honour Ctrl+C-style stops
        names.append("SIGINT")
    for name in names:
        sig = getattr(signal, name, None)
        if sig is not None:
            try:
                signal.signal(sig, handler)
            except (OSError, ValueError):
                pass


def main(argv: list[str] | None = None) -> int:
    _stop_on_signals()
    ap = argparse.ArgumentParser(prog="start-studio", description="Start Alien Time Listing Studio")
    ap.add_argument("mode", nargs="?", choices=["run", "dev"], default="run",
                    help="run (default) or dev (live-reloading backend + Vite dev server)")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--no-browser", action="store_true", help="do not open the browser")
    ap.add_argument("--reinstall", action="store_true", help="reinstall the Python packages")
    ap.add_argument("--rebuild", action="store_true", help="rebuild the web interface (needs Node.js)")
    a = ap.parse_args(argv)
    dev = a.mode == "dev"

    if sys.version_info < MIN_PYTHON:
        fail(f"Python {MIN_PYTHON[0]}.{MIN_PYTHON[1]} or newer is needed (this is {sys.version.split()[0]}). "
             "Install it from https://www.python.org/downloads/ and run the launcher again.", 2)

    say("Alien Time Listing Studio")
    say("-" * 60)
    os.chdir(ROOT)
    port, running = choose_port(a.port)
    url = f"http://{HOST}:{port}"
    if running and not dev:
        say(f"The studio is already running at {url} - opening it.")
        if not a.no_browser:
            webbrowser.open(url)
        return 0
    if running and dev:
        fail(f"A studio is already running on port {port}. Close it first, or use --port to pick another port.")

    ensure_venv()
    ensure_packages(a.reinstall)
    env_values = ensure_env_file()
    ensure_web_build(a.rebuild, dev)

    env = dict(os.environ)
    env["PYTHONUNBUFFERED"] = "1"
    base = env_values.get("STUDIO_BASE_URL", "")
    if port != 8000 and base in ("", "http://127.0.0.1:8000", "http://localhost:8000"):
        env["STUDIO_BASE_URL"] = url  # links in notifications should point at the real address

    cmd = [str(VENV_PY), "-m", "uvicorn", "app.main:app", "--host", HOST, "--port", str(port)]
    if dev:
        cmd += ["--reload", "--reload-dir", str(ROOT / "app")]
    say(f"Starting the studio on {url} (this computer only) ...")
    server = spawn(cmd, ROOT, env)
    vite = None
    try:
        deadline = time.time() + 240
        while not health(port):
            if server.poll() is not None:
                fail("The studio stopped while starting (see the messages above).")
            if time.time() > deadline:
                fail("The studio did not answer within 4 minutes (see the messages above).")
            time.sleep(0.7)
        open_url = url
        if dev:
            npm = npm_path()
            assert npm
            vite_env = dict(env, STUDIO_API_URL=url)
            vite = spawn([npm, "run", "dev", "--", "--port", "5173", "--strictPort"], FRONTEND, vite_env)
            open_url = "http://127.0.0.1:5173"
            for _ in range(60):
                if not port_free(5173):
                    break
                if vite.poll() is not None:
                    fail("The Vite dev server did not start (is port 5173 busy?).")
                time.sleep(0.5)
        say("")
        say(f"Ready: {open_url}")
        if dev:
            say(f"Backend (API, live reload): {url}   Frontend (Vite, hot reload): {open_url}")
        say("Keep this window open while you use the studio. Close it or press Ctrl+C to stop.")
        say("")
        if not a.no_browser:
            webbrowser.open(open_url)
        while True:
            if server.poll() is not None:
                say("The studio has stopped.")
                return server.returncode or 0
            if vite is not None and vite.poll() is not None:
                say("The Vite dev server has stopped; stopping the backend too.")
                return 1
            time.sleep(1)
    except KeyboardInterrupt:
        say("Stopping ...")
        return 0
    finally:
        stop(vite)
        stop(server)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        say("Stopped.")
        sys.exit(130)
