#!/usr/bin/env python3
"""Launch University Research Discovery with one command.

    python main.py

The launcher checks dependencies and configuration, checks Ollama, starts the
local FastAPI server, waits until it is ready, opens Google Chrome, and keeps
running until interrupted.
"""

from __future__ import annotations

import argparse
import importlib
import logging
import os
import shutil
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent

REQUIRED_MODULES = {
    "fastapi": "fastapi",
    "uvicorn": "uvicorn",
    "scrapy": "scrapy",
    "bs4": "beautifulsoup4",
    "lxml": "lxml",
    "reportlab": "reportlab",
    "requests": "requests",
    "yaml": "PyYAML",
    "tldextract": "tldextract",
}


def check_dependencies() -> bool:
    missing = []
    for module, package in REQUIRED_MODULES.items():
        try:
            importlib.import_module(module)
        except (ImportError, OSError):
            missing.append(package)
    if not missing:
        return True
    print("\nMissing required Python packages:")
    for package in missing:
        print(f"  - {package}")
    print("\nInstall them with:")
    print(f"  {sys.executable} -m pip install -r {BASE_DIR / 'requirements.txt'}")
    print("\nThen run: python main.py\n")
    return False


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="University Research Discovery")
    parser.add_argument("--host", help="Host to bind (default from config.yaml)")
    parser.add_argument("--port", type=int, help="Port to bind (default from config.yaml)")
    parser.add_argument(
        "--no-browser", action="store_true", help="Do not open a browser automatically"
    )
    return parser.parse_args()


def port_is_available(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind((host, port))
            return True
        except OSError:
            return False


def choose_port(host: str, preferred: int) -> int:
    if port_is_available(host, preferred):
        return preferred
    for candidate in range(preferred + 1, preferred + 31):
        if port_is_available(host, candidate):
            logging.getLogger("urd").warning(
                "Port %s is in use; using %s instead.", preferred, candidate
            )
            return candidate
    raise RuntimeError(f"No free port found between {preferred} and {preferred + 30}.")


def find_chrome(configured_path: str = "") -> str:
    candidates = []
    if configured_path:
        candidates.append(configured_path)
    candidates.extend(
        [
            "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
            str(
                Path.home()
                / "Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
            ),
            os.path.expandvars(r"%ProgramFiles%\Google\Chrome\Application\chrome.exe"),
            os.path.expandvars(
                r"%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe"
            ),
            os.path.expandvars(r"%LocalAppData%\Google\Chrome\Application\chrome.exe"),
        ]
    )
    for command in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser"):
        found = shutil.which(command)
        if found:
            candidates.append(found)
    for candidate in candidates:
        if candidate and Path(candidate).exists():
            return candidate
    return ""


def open_browser(url: str, chrome_path: str = "") -> str:
    chrome = find_chrome(chrome_path)
    if chrome:
        try:
            subprocess.Popen(
                [chrome, "--new-window", url],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            return "chrome"
        except OSError:
            logging.getLogger("urd").exception("Could not launch Chrome")
    try:
        webbrowser.open(url)
        return "default-browser"
    except Exception:
        logging.getLogger("urd").exception("Could not open the default browser")
        return "none"


def wait_for_server(url: str, timeout: float = 30.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=1.0) as response:
                if response.status == 200:
                    return True
        except (urllib.error.URLError, ConnectionError, TimeoutError, OSError):
            time.sleep(0.25)
    return False


def main() -> int:
    if not check_dependencies():
        return 1

    import uvicorn

    from app.backend.api import create_app
    from app.backend.scan_manager import ScanManager
    from app.config import ensure_directories, load_config
    from app.logging_setup import setup_logging
    from app.utils import display_datetime

    args = parse_args()
    os.chdir(BASE_DIR)
    config = load_config()
    if args.host:
        config["app"]["host"] = args.host
    if args.port:
        config["app"]["port"] = args.port
    ensure_directories(config)
    logger = setup_logging(config)

    host = str(config["app"]["host"])
    port = choose_port(host, int(config["app"]["port"]))
    url = f"http://{host}:{port}"

    manager = ScanManager(config)
    app = create_app(config, manager)
    try:
        ollama_status = manager.health()
    except Exception:
        logger.exception("Initial Ollama check failed")
        ollama_status = {"available": False, "message": "Ollama check failed."}

    print("\n" + "=" * 68)
    print("  University Research Discovery")
    print("=" * 68)
    print(f"  URL:        {url}")
    print(f"  Python:     {sys.executable}")
    print(f"  Working:    {os.getcwd()}")
    print(f"  Outputs:    {config['output']['directory']}")
    print(f"  Logs:       {config['logging']['directory']}/app.log")
    if ollama_status.get("available") and ollama_status.get("model_installed"):
        print(f"  Local AI:   Ollama ready ({config['ollama']['model']})")
    elif ollama_status.get("available"):
        print(f"  Local AI:   Ollama running, model missing ({config['ollama']['model']})")
        for instruction in ollama_status.get("setup_instructions", []):
            print(f"              {instruction}")
    else:
        print("  Local AI:   Ollama unavailable; crawling and reports will still work.")
        for instruction in ollama_status.get("setup_instructions", []):
            print(f"              {instruction}")
    print("=" * 68)
    print("  Press Ctrl+C to stop.\n")

    server = uvicorn.Server(
        uvicorn.Config(
            app,
            host=host,
            port=port,
            log_level="info",
            access_log=False,
            log_config=None,
        )
    )
    server_thread = threading.Thread(target=server.run, name="uvicorn", daemon=True)
    server_thread.start()

    if not wait_for_server(f"{url}/api/health", timeout=30):
        logger.error("The server did not become ready within 30 seconds.")
        print("\nThe local server did not start. See logs/app.log for details.\n")
        server.should_exit = True
        return 1

    logger.info("Server ready at %s", url)
    if not args.no_browser and config["app"].get("open_browser", True):
        opened_with = open_browser(url, config["app"].get("chrome_path", ""))
        logger.info("Browser launch method: %s", opened_with)
        if opened_with == "none":
            print(f"Open this URL in your browser: {url}")
    else:
        print(f"Browser launch skipped. Open: {url}")

    try:
        while server_thread.is_alive():
            time.sleep(0.75)
    except KeyboardInterrupt:
        print("\nStopping University Research Discovery...")
        server.should_exit = True
        server_thread.join(timeout=10)
    return 0


if __name__ == "__main__":
    sys.exit(main())
