"""
Trading Terminal Launcher
==========================
Starts FastAPI backend + Streamlit frontend as two separate processes.

Usage:
  python start.py                  # start both
  python start.py --backend-only   # FastAPI only
  python start.py --frontend-only  # Streamlit only
  python start.py --port-api 8001  # custom API port
"""

import argparse
import subprocess
import sys
import time
import os
import signal
from typing import List

DEFAULT_API_PORT   = 8000
DEFAULT_ST_PORT    = 8501
BACKEND_MODULE     = "backend.main:app"
FRONTEND_ENTRY     = "main.py"


def _python() -> str:
    return sys.executable


def _start_backend(port: int) -> subprocess.Popen:
    cmd = [
        _python(), "-m", "uvicorn",
        BACKEND_MODULE,
        "--host", "0.0.0.0",
        "--port", str(port),
        "--log-level", "info",
        "--no-access-log",
    ]
    print(f"\n[BACKEND]  Starting FastAPI on http://0.0.0.0:{port}")
    print(f"           WS endpoint: ws://localhost:{port}/ws/{{symbol}}/{{timeframe}}")
    return subprocess.Popen(cmd, cwd=os.path.dirname(__file__))


def _start_frontend(port: int) -> subprocess.Popen:
    cmd = [
        _python(), "-m", "streamlit", "run", FRONTEND_ENTRY,
        "--server.port", str(port),
        "--server.headless", "true",
        "--browser.gatherUsageStats", "false",
    ]
    print(f"\n[FRONTEND] Starting Streamlit on http://localhost:{port}")
    return subprocess.Popen(cmd, cwd=os.path.dirname(__file__))


def _wait_for_backend(port: int, timeout: float = 30.0) -> bool:
    """Poll until FastAPI is accepting connections."""
    import urllib.request
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            urllib.request.urlopen(f"http://localhost:{port}/api/status", timeout=1)
            return True
        except Exception:
            time.sleep(0.5)
    return False


def main():
    parser = argparse.ArgumentParser(description="Trading Terminal Launcher")
    parser.add_argument("--backend-only",  action="store_true")
    parser.add_argument("--frontend-only", action="store_true")
    parser.add_argument("--port-api", type=int, default=DEFAULT_API_PORT)
    parser.add_argument("--port-ui",  type=int, default=DEFAULT_ST_PORT)
    args = parser.parse_args()

    procs: List[subprocess.Popen] = []

    def _shutdown(sig=None, frame=None):
        print("\n[SHUTDOWN] Stopping processes …")
        for p in procs:
            try:
                p.terminate()
            except Exception:
                pass
        for p in procs:
            try:
                p.wait(timeout=5)
            except Exception:
                p.kill()
        print("[SHUTDOWN] Done.")
        sys.exit(0)

    signal.signal(signal.SIGINT,  _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    try:
        if not args.frontend_only:
            api_proc = _start_backend(args.port_api)
            procs.append(api_proc)

            print("[BACKEND]  Waiting for API to come online …", end="", flush=True)
            if _wait_for_backend(args.port_api):
                print(" ready.")
            else:
                print(" timeout — continuing anyway.")

        if not args.backend_only:
            ui_proc = _start_frontend(args.port_ui)
            procs.append(ui_proc)

        print("\n" + "="*60)
        print("  Trading Terminal is running")
        if not args.frontend_only:
            print(f"  API:  http://localhost:{args.port_api}/api/status")
            print(f"  Docs: http://localhost:{args.port_api}/docs")
        if not args.backend_only:
            print(f"  UI:   http://localhost:{args.port_ui}")
        print("  Press Ctrl+C to stop both processes")
        print("="*60 + "\n")

        # Wait for any process to exit
        while True:
            for p in procs:
                rc = p.poll()
                if rc is not None:
                    print(f"\n[WARNING] A process exited with code {rc}. Shutting down.")
                    _shutdown()
            time.sleep(1)

    except KeyboardInterrupt:
        _shutdown()


if __name__ == "__main__":
    main()
