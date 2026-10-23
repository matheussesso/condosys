"""Assisted login: browser discovery, waiting for the person and the takeover."""

import http.server
import json
import threading
from collections.abc import Iterator
from pathlib import Path
from typing import ClassVar

import pytest
from playwright.sync_api import sync_playwright

from condosys.assisted_browser import (
    AssistedLoginError,
    find_browser_executable,
    wait_for_portal_tab,
)
from condosys.models import AccessMode, Condominium
from condosys.portals.issnet.session import issnet_session
from condosys.settings import Settings
from tests.conftest import THE_SUN_CNPJ
from tests.test_browser import _make_portal_handler


def test_explicit_browser_path(tmp_path: Path) -> None:
    exe = tmp_path / "chrome"
    exe.write_bytes(b"")
    assert find_browser_executable(Settings(base_dir=tmp_path, assisted_browser_path=exe)) == exe
    with pytest.raises(AssistedLoginError, match="não encontrado"):
        find_browser_executable(
            Settings(base_dir=tmp_path, assisted_browser_path=tmp_path / "nope")
        )


def test_browser_found_on_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("sys.platform", "linux")
    found = {"google-chrome": None, "chromium": "/usr/bin/chromium"}
    monkeypatch.setattr("shutil.which", lambda name: found.get(name))
    settings = Settings(base_dir=tmp_path, browser_channel="chromium")
    assert find_browser_executable(settings) == Path("/usr/bin/chromium")
    monkeypatch.setattr("shutil.which", lambda name: None)
    with pytest.raises(AssistedLoginError, match="Chrome/Edge não encontrado"):
        find_browser_executable(settings)


class _DevToolsHandler(http.server.BaseHTTPRequestHandler):
    targets: ClassVar[list[dict[str, str]]] = []

    def do_GET(self) -> None:
        body = json.dumps(self.targets).encode()
        self.send_response(200)
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:
        pass


@pytest.fixture
def devtools() -> Iterator[tuple[int, type[_DevToolsHandler]]]:
    handler = type("Handler", (_DevToolsHandler,), {"targets": []})
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield server.server_address[1], handler
    server.shutdown()
    server.server_close()


def test_wait_for_portal_tab(devtools: tuple[int, type[_DevToolsHandler]]) -> None:
    port, handler = devtools
    portal = "https://iss.fazenda.df.gov.br"
    handler.targets = [
        {"type": "page", "url": f"{portal}/online/Login/Login.aspx?ReturnUrl=%2fonline"},
        {"type": "page", "url": "https://api.ihub.com.br/auth?token=x"},
    ]
    with pytest.raises(AssistedLoginError, match="não foi concluído"):
        wait_for_portal_tab(port, portal, timeout_s=0.3, poll_s=0.1)

    handler.targets.append({"type": "page", "url": f"{portal}/online/default/empresas.aspx?x"})
    assert wait_for_portal_tab(port, portal, timeout_s=2, poll_s=0.1).endswith("empresas.aspx?x")


@pytest.mark.browser
def test_assisted_login_takeover(tmp_path: Path) -> None:
    with sync_playwright() as playwright:
        executable = Path(playwright.chromium.executable_path)
    if not executable.is_file():
        pytest.skip("Chromium indisponível")

    server = http.server.ThreadingHTTPServer(
        ("localhost", 0), _make_portal_handler("https://ihub.invalid")
    )
    threading.Thread(target=server.serve_forever, daemon=True).start()
    portal = f"http://localhost:{server.server_address[1]}"
    settings = Settings(
        base_dir=tmp_path,
        login_mode="assisted",
        assisted_browser_path=executable,
        assisted_browser_args=["--headless=new"],
        assisted_login_timeout_ms=20_000,
        issnet_login_url=f"{portal}/online/Login/Pessoa.aspx",
    )
    condominium = Condominium(
        active=True,
        name="The Sun Full Condominium Resort",
        cnpj=THE_SUN_CNPJ,
        access_mode=AccessMode.DIRECT,
        certificate="the-sun.pfx",
    )
    try:
        with issnet_session(settings, condominium) as session:
            assert session.assisted
            session.login()
            assert "/online/Default.aspx" in session.page.url
            assert session.check_identity(condominium).confirmed
    finally:
        server.shutdown()
        server.server_close()
    assert (tmp_path / "browser-profile").is_dir()
