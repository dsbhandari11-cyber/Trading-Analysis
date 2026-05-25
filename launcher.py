"""
Trading Terminal Launcher v2
============================
One-command startup for FastAPI backend + React/Vite frontend.

Usage:
  python launcher.py              # start everything
  python launcher.py --stop       # kill all services
  python launcher.py --restart    # stop then start
  python launcher.py --status     # show port/process status
  python launcher.py --backend    # backend only
  python launcher.py --frontend   # frontend only (assumes backend running)
  python launcher.py --no-browser # don't open browser automatically
  python launcher.py --no-watchdog # disable crash recovery

Logs:
  logs/backend.log    FastAPI stdout+stderr
  logs/frontend.log   Vite stdout+stderr
  logs/launcher.log   Launcher events
"""

from __future__ import annotations

import argparse
import ctypes
import json
import logging
import os
import shutil
import signal
import socket
import subprocess
import sys
import threading
import time
import urllib.request
import webbrowser
from datetime import datetime
from pathlib import Path

# Force UTF-8 output on Windows so box-drawing chars render correctly
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except AttributeError:
        pass


# ── ANSI colours (enabled on Windows 10 via kernel32 call) ────────────────────

def _enable_ansi_windows() -> None:
    """Turn on VT-100 processing for Windows console."""
    try:
        k32 = ctypes.windll.kernel32
        # ENABLE_VIRTUAL_TERMINAL_PROCESSING = 0x0004
        handle = k32.GetStdHandle(-11)  # STD_OUTPUT_HANDLE
        mode = ctypes.c_ulong()
        k32.GetConsoleMode(handle, ctypes.byref(mode))
        k32.SetConsoleMode(handle, mode.value | 0x0004)
    except Exception:
        pass


_enable_ansi_windows()


class C:
    RESET  = "\033[0m"
    BOLD   = "\033[1m"
    DIM    = "\033[2m"
    RED    = "\033[91m"
    GREEN  = "\033[92m"
    YELLOW = "\033[93m"
    BLUE   = "\033[94m"
    PURPLE = "\033[95m"
    CYAN   = "\033[96m"
    WHITE  = "\033[97m"


def _c(text: str, *codes: str) -> str:
    return "".join(codes) + text + C.RESET


# ── Paths ──────────────────────────────────────────────────────────────────────

ROOT      = Path(__file__).resolve().parent
FRONTEND  = ROOT / "frontend"
LOGS_DIR  = ROOT / "logs"
PIDS_FILE = ROOT / "logs" / ".pids.json"

BACKEND_PORT  = 8000
FRONTEND_PORT = 3000

HEALTH_URL   = f"http://127.0.0.1:{BACKEND_PORT}/api/status"
FRONTEND_URL = f"http://127.0.0.1:{FRONTEND_PORT}"


# ── Logging setup ──────────────────────────────────────────────────────────────

def _setup_logging() -> logging.Logger:
    LOGS_DIR.mkdir(exist_ok=True)
    log = logging.getLogger("launcher")
    log.setLevel(logging.DEBUG)
    # File handler — full detail
    fh = logging.FileHandler(LOGS_DIR / "launcher.log", encoding="utf-8")
    fh.setFormatter(logging.Formatter("%(asctime)s  %(levelname)-7s  %(message)s"))
    log.addHandler(fh)
    # No stream handler — we print manually for coloured output
    return log


log = _setup_logging()


# ── Helpers ────────────────────────────────────────────────────────────────────

def _ts() -> str:
    return datetime.now().strftime("%H:%M:%S")


def _print(tag: str, msg: str, color: str = C.WHITE) -> None:
    line = f"{_c(_ts(), C.DIM)}  {_c(tag, C.BOLD, color)}  {msg}"
    print(line)
    log.info("[%s] %s", tag.strip(), msg)


def _ok(msg: str)    -> None: _print(" OK  ", msg, C.GREEN)
def _info(msg: str)  -> None: _print(" -- ", msg, C.CYAN)
def _warn(msg: str)  -> None: _print("WARN ", msg, C.YELLOW)
def _err(msg: str)   -> None: _print(" ERR ", msg, C.RED)
def _step(msg: str)  -> None: _print("  »  ", msg, C.BLUE)


def _splash() -> None:
    width = 62
    border = _c("═" * width, C.CYAN, C.BOLD)
    print()
    print(border)
    print(_c("  ▸ BHANDARI TRADING TERMINAL  ", C.BOLD, C.CYAN) +
          _c("  v2  " + datetime.now().strftime("%Y-%m-%d"), C.DIM))
    print(_c(f"  Backend  →  http://127.0.0.1:{BACKEND_PORT}", C.DIM))
    print(_c(f"  Frontend →  http://127.0.0.1:{FRONTEND_PORT}", C.DIM))
    print(border)
    print()


def _find_python() -> str:
    """Prefer venv python, fall back to system python."""
    venv_py = ROOT / ".venv" / "Scripts" / "python.exe"
    if venv_py.exists():
        return str(venv_py)
    return sys.executable


def _find_npm() -> str | None:
    """Locate npm executable on Windows."""
    for name in ("npm.cmd", "npm"):
        path = shutil.which(name)
        if path:
            return path
    return None


def _port_in_use(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.3)
        return s.connect_ex(("127.0.0.1", port)) == 0


def _kill_port(port: int) -> None:
    """Kill whatever process is listening on *port* (Windows netstat approach)."""
    try:
        result = subprocess.run(
            ["netstat", "-ano"],
            capture_output=True, text=True, timeout=10
        )
        for line in result.stdout.splitlines():
            if f":{port} " in line and "LISTENING" in line:
                parts = line.split()
                pid = int(parts[-1])
                if pid > 4:  # skip System process (PID 4)
                    subprocess.run(["taskkill", "/F", "/PID", str(pid)],
                                   capture_output=True)
                    _info(f"Killed PID {pid} on port {port}")
    except Exception as exc:
        _warn(f"Could not kill port {port}: {exc}")


def _wait_http(url: str, timeout: float = 45.0, interval: float = 0.5) -> bool:
    """Poll *url* until it returns HTTP 200 or *timeout* seconds elapse."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2) as resp:
                if resp.status < 400:
                    return True
        except Exception:
            pass
        time.sleep(interval)
    return False


# ── PID registry (persisted across invocations for stop/restart) ──────────────

def _save_pids(pids: dict[str, int]) -> None:
    LOGS_DIR.mkdir(exist_ok=True)
    PIDS_FILE.write_text(json.dumps(pids))


def _load_pids() -> dict[str, int]:
    try:
        return json.loads(PIDS_FILE.read_text())
    except Exception:
        return {}


def _kill_saved_pids() -> None:
    pids = _load_pids()
    for name, pid in pids.items():
        try:
            subprocess.run(["taskkill", "/F", "/PID", str(pid)],
                           capture_output=True)
            _info(f"Killed saved PID {pid} ({name})")
        except Exception:
            pass
    if pids:
        PIDS_FILE.unlink(missing_ok=True)


# ── Service management ────────────────────────────────────────────────────────

class ServiceProcess:
    """Wraps a subprocess and handles log capture + watchdog restart."""

    def __init__(
        self,
        name: str,
        cmd: list[str],
        cwd: Path,
        log_file: Path,
        color: str,
        auto_restart: bool = True,
    ):
        self.name         = name
        self.cmd          = cmd
        self.cwd          = cwd
        self.log_file     = log_file
        self.color        = color
        self.auto_restart = auto_restart
        self._proc: subprocess.Popen | None = None
        self._log_fh      = None
        self._lock        = threading.Lock()
        self.crash_count  = 0
        self.started_at   = 0.0

    def _tag(self, msg: str) -> None:
        _print(f"[{self.name}]", msg, self.color)

    def start(self) -> bool:
        with self._lock:
            LOGS_DIR.mkdir(exist_ok=True)
            self._log_fh = open(self.log_file, "a", encoding="utf-8")
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            self._log_fh.write(f"\n{'='*60}\n  Start: {timestamp}\n{'='*60}\n")
            self._log_fh.flush()

            try:
                self._proc = subprocess.Popen(
                    self.cmd,
                    cwd=self.cwd,
                    stdout=self._log_fh,
                    stderr=self._log_fh,
                    creationflags=subprocess.CREATE_NO_WINDOW
                    if sys.platform == "win32" else 0,
                )
                self.started_at = time.monotonic()
                self._tag(f"PID {self._proc.pid}  log → {self.log_file.name}")
                return True
            except Exception as exc:
                _err(f"Failed to start {self.name}: {exc}")
                return False

    def stop(self) -> None:
        with self._lock:
            if self._proc and self._proc.poll() is None:
                self._proc.terminate()
                try:
                    self._proc.wait(timeout=6)
                except subprocess.TimeoutExpired:
                    self._proc.kill()
            if self._log_fh:
                try:
                    self._log_fh.close()
                except Exception:
                    pass
            self._proc = None

    @property
    def pid(self) -> int | None:
        return self._proc.pid if self._proc else None

    @property
    def alive(self) -> bool:
        return bool(self._proc and self._proc.poll() is None)


# ── Main launcher class ────────────────────────────────────────────────────────

class TradingTerminalLauncher:

    def __init__(self, args: argparse.Namespace):
        self.args          = args
        self._services: list[ServiceProcess] = []
        self._watchdog_thr: threading.Thread | None = None
        self._running      = threading.Event()

    # ── Build service definitions ─────────────────────────────────────────────

    def _make_backend(self) -> ServiceProcess:
        py  = _find_python()
        cmd = [
            py, "-m", "uvicorn",
            "backend.main:app",
            "--host", "127.0.0.1",
            "--port", str(BACKEND_PORT),
            "--log-level", "info",
        ]
        return ServiceProcess(
            name="BACKEND",
            cmd=cmd,
            cwd=ROOT,
            log_file=LOGS_DIR / "backend.log",
            color=C.GREEN,
        )

    def _make_frontend(self) -> ServiceProcess:
        npm = _find_npm()
        if not npm:
            raise RuntimeError("npm not found. Install Node.js and try again.")
        cmd = [npm, "run", "dev", "--", "--host", "127.0.0.1", "--port", str(FRONTEND_PORT)]
        return ServiceProcess(
            name="FRONTEND",
            cmd=cmd,
            cwd=FRONTEND,
            log_file=LOGS_DIR / "frontend.log",
            color=C.BLUE,
        )

    # ── Pre-flight checks ─────────────────────────────────────────────────────

    def _preflight(self, need_backend: bool, need_frontend: bool) -> bool:
        _step("Running pre-flight checks …")

        py = _find_python()
        _ok(f"Python  →  {py}")

        if need_frontend:
            npm = _find_npm()
            if not npm:
                _err("npm not found. Install Node.js from https://nodejs.org")
                return False
            _ok(f"npm     →  {npm}")

            if not (FRONTEND / "package.json").exists():
                _err(f"package.json not found in {FRONTEND}")
                return False

            if not (FRONTEND / "node_modules").exists():
                _warn("node_modules missing — running npm install …")
                result = subprocess.run(
                    [npm, "install"],
                    cwd=FRONTEND,
                    capture_output=True, text=True, timeout=120,
                )
                if result.returncode != 0:
                    _err(f"npm install failed:\n{result.stderr[:400]}")
                    return False
                _ok("npm install complete")

        if need_backend:
            if not (ROOT / "backend" / "main.py").exists():
                _err(f"backend/main.py not found in {ROOT}")
                return False

            result = subprocess.run(
                [py, "-c", "import fastapi, uvicorn; import backend.main"],
                cwd=ROOT,
                capture_output=True,
                text=True,
                timeout=25,
            )
            if result.returncode != 0:
                details = (result.stderr or result.stdout).strip()
                if details:
                    details = "\n" + details[-1200:]
                _err(
                    "Backend import check failed. Run "
                    f"`{py} -m pip install -r requirements.txt` and try again."
                    f"{details}"
                )
                return False
            _ok("Backend imports")

        return True

    # ── Startup sequence ──────────────────────────────────────────────────────

    def start(self) -> None:
        _splash()

        want_backend  = not self.args.frontend_only
        want_frontend = not self.args.backend_only

        if not self._preflight(want_backend, want_frontend):
            sys.exit(1)

        # Kill whatever is already occupying the ports
        if want_backend and _port_in_use(BACKEND_PORT):
            _warn(f"Port {BACKEND_PORT} occupied — clearing …")
            _kill_port(BACKEND_PORT)
            time.sleep(0.8)

        if want_frontend and _port_in_use(FRONTEND_PORT):
            _warn(f"Port {FRONTEND_PORT} occupied — clearing …")
            _kill_port(FRONTEND_PORT)
            time.sleep(0.8)

        # ── Backend ───────────────────────────────────────────────────────────
        if want_backend:
            be = self._make_backend()
            self._services.append(be)
            _step("Starting FastAPI backend …")
            if not be.start():
                _err("Backend failed to launch. Check logs/backend.log")
                sys.exit(1)

            _step(f"Waiting for backend health check ({HEALTH_URL}) …")
            dots = 0
            backend_ready = False
            deadline = time.monotonic() + 40
            while time.monotonic() < deadline:
                if not be.alive:
                    print()
                    _err("Backend exited before health check completed. Check logs/backend.log")
                    be.stop()
                    sys.exit(1)
                try:
                    with urllib.request.urlopen(HEALTH_URL, timeout=2) as r:
                        if r.status < 400:
                            backend_ready = True
                            break
                except Exception:
                    pass
                print(_c(".", C.DIM), end="", flush=True)
                dots += 1
                time.sleep(0.6)

            if not backend_ready:
                print()
                _err("Backend health check timed out. Check logs/backend.log")
                be.stop()
                sys.exit(1)
            print()
            _ok(f"Backend ready  →  http://127.0.0.1:{BACKEND_PORT}")
            _ok(f"API docs       →  http://127.0.0.1:{BACKEND_PORT}/docs")

        # ── Frontend ──────────────────────────────────────────────────────────
        if want_frontend:
            fe = self._make_frontend()
            self._services.append(fe)
            _step("Starting React/Vite frontend …")
            if not fe.start():
                _err("Frontend failed to launch. Check logs/frontend.log")
                sys.exit(1)

            _step(f"Waiting for Vite dev server ({FRONTEND_URL}) …")
            dots = 0
            deadline = time.monotonic() + 40
            while time.monotonic() < deadline:
                try:
                    with urllib.request.urlopen(FRONTEND_URL, timeout=2) as r:
                        if r.status < 400:
                            break
                except Exception:
                    pass
                print(_c(".", C.DIM), end="", flush=True)
                dots += 1
                time.sleep(0.6)
            else:
                print()
                _warn("Frontend health check timed out — trying to open browser anyway.")
            print()
            _ok(f"Frontend ready →  {FRONTEND_URL}")

        # ── Persist PIDs ─────────────────────────────────────────────────────
        _save_pids({s.name: s.pid for s in self._services if s.pid})

        # ── Browser ──────────────────────────────────────────────────────────
        if want_frontend and not self.args.no_browser:
            time.sleep(0.4)
            _step("Opening browser …")
            webbrowser.open(FRONTEND_URL)

        # ── Summary ──────────────────────────────────────────────────────────
        width = 62
        print()
        print(_c("═" * width, C.GREEN, C.BOLD))
        print(_c("  ✔ TRADING TERMINAL IS LIVE", C.BOLD, C.GREEN))
        if want_backend:
            print(f"  {_c('Backend ', C.DIM)}  http://127.0.0.1:{BACKEND_PORT}/docs")
        if want_frontend:
            print(f"  {_c('Frontend', C.DIM)}  {FRONTEND_URL}")
        print(f"  {_c('Logs    ', C.DIM)}  {LOGS_DIR}")
        print(_c("  Press Ctrl+C to stop all services", C.DIM))
        print(_c("═" * width, C.GREEN, C.BOLD))
        print()

        # ── Watchdog ─────────────────────────────────────────────────────────
        if not self.args.no_watchdog:
            self._running.set()
            self._watchdog_thr = threading.Thread(
                target=self._watchdog_loop, daemon=True
            )
            self._watchdog_thr.start()

        self._wait_loop()

    # ── Watchdog ──────────────────────────────────────────────────────────────

    def _watchdog_loop(self) -> None:
        MAX_RESTARTS = 5
        COOLDOWN     = 5.0   # seconds between restart attempts

        while self._running.is_set():
            time.sleep(3)
            for svc in self._services:
                if not svc.alive and svc.auto_restart and self._running.is_set():
                    svc.crash_count += 1
                    if svc.crash_count > MAX_RESTARTS:
                        _err(f"{svc.name} crashed {MAX_RESTARTS}+ times — giving up auto-restart")
                        svc.auto_restart = False
                        continue
                    uptime = time.monotonic() - svc.started_at
                    _warn(
                        f"{svc.name} exited after {uptime:.0f}s "
                        f"(restart #{svc.crash_count}/{MAX_RESTARTS})"
                    )
                    time.sleep(COOLDOWN)
                    if not self._running.is_set():
                        break
                    _step(f"Restarting {svc.name} …")
                    svc.start()

    # ── Wait / shutdown ───────────────────────────────────────────────────────

    def _wait_loop(self) -> None:
        def _shutdown(sig=None, frame=None) -> None:
            print()
            _info("Shutdown signal received …")
            self._running.clear()
            for svc in self._services:
                svc.auto_restart = False
                _step(f"Stopping {svc.name} (PID {svc.pid}) …")
                svc.stop()
            _kill_port(BACKEND_PORT)
            _kill_port(FRONTEND_PORT)
            PIDS_FILE.unlink(missing_ok=True)
            _ok("All services stopped. Goodbye.")
            sys.exit(0)

        signal.signal(signal.SIGINT,  _shutdown)
        signal.signal(signal.SIGTERM, _shutdown)

        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            _shutdown()

    # ── Stop command ──────────────────────────────────────────────────────────

    @staticmethod
    def stop_all() -> None:
        _splash()
        _step("Stopping all Trading Terminal services …")
        _kill_saved_pids()
        _kill_port(BACKEND_PORT)
        _kill_port(FRONTEND_PORT)
        PIDS_FILE.unlink(missing_ok=True)
        _ok("All services stopped.")

    # ── Status command ────────────────────────────────────────────────────────

    @staticmethod
    def show_status() -> None:
        print()
        be_up = _port_in_use(BACKEND_PORT)
        fe_up = _port_in_use(FRONTEND_PORT)

        def _svc_line(name: str, port: int, up: bool) -> None:
            status = _c("● RUNNING", C.GREEN, C.BOLD) if up else _c("○ STOPPED", C.DIM)
            print(f"  {name:<12}  port {port}   {status}")

        print(_c("  Service Status", C.BOLD, C.CYAN))
        print(_c("  " + "─" * 40, C.DIM))
        _svc_line("Backend",  BACKEND_PORT,  be_up)
        _svc_line("Frontend", FRONTEND_PORT, fe_up)
        print()

        if be_up:
            print(f"  {_c('Backend API docs', C.DIM)}  http://127.0.0.1:{BACKEND_PORT}/docs")
        if fe_up:
            print(f"  {_c('Frontend URL    ', C.DIM)}  {FRONTEND_URL}")
        print()


# ── Entry point ───────────────────────────────────────────────────────────────

def main() -> None:
    p = argparse.ArgumentParser(
        description="Bhandari Trading Terminal — one-command launcher",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--stop",        action="store_true", help="Kill all services")
    p.add_argument("--restart",     action="store_true", help="Stop then start all services")
    p.add_argument("--status",      action="store_true", help="Show service status")
    p.add_argument("--backend",       dest="backend_only",  action="store_true",
                   default=False,     help="Backend only")
    p.add_argument("--frontend",      dest="frontend_only", action="store_true",
                   default=False,     help="Frontend only")
    p.add_argument("--backend-only",  dest="backend_only",  action="store_true")
    p.add_argument("--frontend-only", dest="frontend_only", action="store_true")
    p.add_argument("--no-browser",    action="store_true", default=False)
    p.add_argument("--no-watchdog",   action="store_true", default=False)
    args = p.parse_args()

    if args.status:
        TradingTerminalLauncher.show_status()
        return

    if args.stop:
        TradingTerminalLauncher.stop_all()
        return

    if args.restart:
        TradingTerminalLauncher.stop_all()
        time.sleep(2)
        # Re-parse without --restart to run startup
        args.stop    = False
        args.restart = False

    launcher = TradingTerminalLauncher(args)
    launcher.start()


if __name__ == "__main__":
    main()
