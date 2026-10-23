"""Assisted login: a person logs in using the regular Chrome/Edge, then condosys takes over.

The iHub authentication popup is protected by Cloudflare, which rejects browsers driven
by automation even when a person ticks "Confirme que é humano" (ADR-009). So condosys:

1. starts the installed Chrome/Edge as a normal process, with its own profile and a local
   DevTools port, and opens the ISSNet login page;
2. waits, without attaching to any page, until a tab is inside the portal — the person
   clicks "Logar com certificado digital", picks the certificate (installed in the
   system/browser certificate store) and answers any check, exactly as today;
3. only then connects through the DevTools protocol to drive the authenticated portal.

Nothing here tries to hide automation or bypass the check: the person does the login.
"""

import json
import logging
import os
import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import urlsplit

from playwright.sync_api import Browser, sync_playwright
from playwright.sync_api import Error as PlaywrightError

from condosys.settings import Settings

logger = logging.getLogger(__name__)

_LINUX_CANDIDATES: dict[str, tuple[str, ...]] = {
    "chrome": ("google-chrome", "google-chrome-stable"),
    "msedge": ("microsoft-edge", "microsoft-edge-stable"),
    "chromium": ("chromium", "chromium-browser"),
}
_WINDOWS_SUFFIXES: dict[str, tuple[str, ...]] = {
    "chrome": (r"Google\Chrome\Application\chrome.exe",),
    "msedge": (r"Microsoft\Edge\Application\msedge.exe",),
    "chromium": (r"Chromium\Application\chrome.exe",),
}
# Preferred order when the channel is "chromium" (no specific browser chosen).
_FALLBACK_ORDER: dict[str, tuple[str, ...]] = {
    "chrome": ("chrome",),
    "msedge": ("msedge",),
    "chromium": ("msedge", "chrome", "chromium")
    if sys.platform == "win32"
    else ("chrome", "chromium", "msedge"),
}


class AssistedLoginError(RuntimeError):
    """Raised when the assisted browser cannot be started or the login does not happen."""


def find_browser_executable(settings: Settings) -> Path:
    """Finds the installed Chrome/Edge to open for the assisted login.

    ``CONDOSYS_ASSISTED_BROWSER_PATH`` wins; otherwise ``browser_channel`` decides.

    Raises:
        AssistedLoginError: If no suitable browser is installed.
    """
    if settings.assisted_browser_path is not None:
        if settings.assisted_browser_path.is_file():
            return settings.assisted_browser_path
        raise AssistedLoginError(f"navegador não encontrado: {settings.assisted_browser_path}")

    for name in _FALLBACK_ORDER[settings.browser_channel]:
        if sys.platform == "win32":
            for env in ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA"):
                root = os.environ.get(env)
                for suffix in _WINDOWS_SUFFIXES[name]:
                    if root and (Path(root) / suffix).is_file():
                        return Path(root) / suffix
        else:
            for command in _LINUX_CANDIDATES[name]:
                found = shutil.which(command)
                if found:
                    return Path(found)
    raise AssistedLoginError(
        "Chrome/Edge não encontrado. Instale o Google Chrome ou o Microsoft Edge, ou "
        "informe o caminho em CONDOSYS_ASSISTED_BROWSER_PATH no .env."
    )


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        port: int = sock.getsockname()[1]
        return port


def _devtools_json(port: int, path: str) -> object:
    # Plain HTTP to the local DevTools endpoint: lists tabs without attaching to them.
    with urllib.request.urlopen(f"http://127.0.0.1:{port}{path}", timeout=2) as response:
        return json.loads(response.read().decode("utf-8"))


def _is_inside_portal(url: str, portal_origin: str) -> bool:
    parts = urlsplit(url)
    path = parts.path.lower()
    # Everything under .../Login/ (e.g. /online/Login/Login.aspx) is still the login area.
    return f"{parts.scheme}://{parts.netloc}" == portal_origin and "/login/" not in path


def wait_for_portal_tab(
    port: int,
    portal_origin: str,
    timeout_s: float,
    process: subprocess.Popen[bytes] | None = None,
    poll_s: float = 1.0,
) -> str:
    """Waits until some browser tab is inside the portal (past the login page).

    Args:
        port: Local DevTools port.
        portal_origin: ``https://host`` of the portal.
        timeout_s: Maximum wait.
        process: Browser process; if it exits, waiting stops.
        poll_s: Interval between checks.

    Returns:
        The URL of the authenticated tab.

    Raises:
        AssistedLoginError: On timeout or if the browser is closed.
    """
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if process is not None and process.poll() is not None:
            raise AssistedLoginError("o navegador foi fechado antes de concluir o login")
        try:
            targets = _devtools_json(port, "/json/list")
        except (OSError, urllib.error.URLError, ValueError):
            targets = []
        for target in targets if isinstance(targets, list) else []:
            url = str(target.get("url", "")) if isinstance(target, dict) else ""
            if target.get("type") == "page" and _is_inside_portal(url, portal_origin):
                return url
        time.sleep(poll_s)
    raise AssistedLoginError(
        f"o login não foi concluído em {int(timeout_s)} s "
        "(CONDOSYS_ASSISTED_LOGIN_TIMEOUT_MS no .env)"
    )


def _wait_for_devtools(port: int, process: subprocess.Popen[bytes], timeout_s: float) -> None:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise AssistedLoginError(
                "o navegador fechou logo ao abrir. Se já houver uma janela do navegador do "
                "condosys aberta (perfil em browser-profile/), feche-a e tente de novo."
            )
        try:
            _devtools_json(port, "/json/version")
            return
        except (OSError, urllib.error.URLError, ValueError):
            time.sleep(0.25)
    raise AssistedLoginError("o navegador não abriu a porta de controle local a tempo")


@contextmanager
def assisted_browser(settings: Settings, start_url: str) -> Iterator[Browser]:
    """Opens the regular Chrome/Edge, waits for a person to log in, then connects to it.

    Args:
        settings: Application settings.
        start_url: Page opened for the person (the ISSNet login page).

    Yields:
        The connected browser, already past the login. The browser process is closed on exit.

    Raises:
        AssistedLoginError: If the browser cannot start or the login does not happen.
    """
    executable = find_browser_executable(settings)
    profile = settings.browser_profile_dir
    profile.mkdir(parents=True, exist_ok=True)
    port = _free_port()
    command = [
        str(executable),
        f"--remote-debugging-port={port}",
        "--remote-debugging-address=127.0.0.1",
        f"--user-data-dir={profile}",
        "--no-first-run",
        "--no-default-browser-check",
        *settings.assisted_browser_args,
        start_url,
    ]
    logger.info("Abrindo %s (perfil %s)", executable.name, profile)
    process = subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        _wait_for_devtools(port, process, timeout_s=20)
        portal_origin = "{0.scheme}://{0.netloc}".format(urlsplit(start_url))
        url = wait_for_portal_tab(
            port, portal_origin, settings.assisted_login_timeout_ms / 1000, process
        )
        logger.info("Login detectado: %s", url.split("?")[0])
        with sync_playwright() as playwright:
            try:
                browser = playwright.chromium.connect_over_cdp(f"http://127.0.0.1:{port}")
            except PlaywrightError as exc:
                raise AssistedLoginError(f"não foi possível assumir o navegador: {exc}") from exc
            try:
                yield browser
            finally:
                browser.close()
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
