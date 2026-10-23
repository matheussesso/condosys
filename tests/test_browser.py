"""Browser tests against local servers (no access to the real portal).

They need Chromium: ``uv run playwright install chromium``. Skipped when it is missing.
"""

import datetime as dt
import http.server
import json
import shutil
import ssl
import threading
import urllib.parse
from collections.abc import Iterator
from pathlib import Path

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from playwright.sync_api import Browser, sync_playwright
from playwright.sync_api import Error as PlaywrightError

from condosys.browser import BrowserSetupError, build_client_certificates, new_certificate_context
from condosys.credentials import save_password
from condosys.models import AccessMode, Condominium
from condosys.portals.issnet import selectors
from condosys.portals.issnet.session import IssnetSession, LoginError
from condosys.recon import PageRecorder
from condosys.settings import Settings
from tests.conftest import PFX_PASSWORD, THE_SUN_CNPJ, make_ca, make_certificate, write_pfx

pytestmark = pytest.mark.browser


@pytest.fixture(scope="module")
def browser() -> Iterator[Browser]:
    with sync_playwright() as playwright:
        try:
            instance = playwright.chromium.launch()
        except Exception as exc:  # browser not installed
            pytest.skip(f"Chromium indisponível: {str(exc).splitlines()[0]}")
        yield instance
        instance.close()


def _pem_files(tmp: Path, key: rsa.RSAPrivateKey, cert: x509.Certificate, name: str) -> Path:
    path = tmp / f"{name}.pem"
    path.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
        + cert.public_bytes(serialization.Encoding.PEM)
    )
    return path


def _server_certificate() -> tuple[rsa.RSAPrivateKey, x509.Certificate]:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "localhost")])
    now = dt.datetime.now(dt.UTC)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - dt.timedelta(days=1))
        .not_valid_after(now + dt.timedelta(days=2))
        .add_extension(x509.SubjectAlternativeName([x509.DNSName("localhost")]), critical=False)
        .sign(key, hashes.SHA256())
    )
    return key, cert


# Fake iHub: answers /auth with a page that posts the ticket (the client certificate CN)
# back to the opener and closes, like https://api.ihub.com.br/auth.
IHUB_AUTH_PAGE = """<html><body><script>
window.opener.postMessage({{ok: true, ticket: {ticket}}}, '*');
window.close();
</script></body></html>"""


IHUB_CHALLENGE_PAGE = """<html><body><iframe src="/turnstile"></iframe><script>
setTimeout(function () {{
  window.opener.postMessage({{ok: true, ticket: {ticket}}}, '*');
  window.close();
}}, 2500);
</script></body></html>"""


class _EchoClientHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        peer = self.connection.getpeercert()  # type: ignore[attr-defined]
        subject = dict(item[0] for item in peer["subject"]) if peer else {}
        common_name = subject.get("commonName", "")
        if self.path.startswith("/auth?token=DESAFIO"):
            # Human check: an iframe from the "challenge" host, solved after a while.
            body = IHUB_CHALLENGE_PAGE.format(ticket=json.dumps(common_name))
        elif self.path.startswith("/turnstile"):
            body = "<html><body><label><input type=checkbox> Confirme que é humano</label>"
        elif self.path.startswith("/auth"):
            body = IHUB_AUTH_PAGE.format(ticket=json.dumps(common_name))
        else:
            body = f"<html><body><p id='cn'>{common_name}</p></body></html>"
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(body.encode())

    def log_message(self, format: str, *args: object) -> None:
        pass


@pytest.fixture
def mtls_server(tmp_path: Path) -> Iterator[tuple[str, Path, Path]]:
    """HTTPS server that requires a client certificate signed by the test 'CA'.

    Yields (origin, modern pfx, legacy pfx).
    """
    ca_key, ca_cert = make_ca()
    client_key, client_cert = make_certificate(
        f"THE SUN FULL CONDOMINIUM RESORT:{THE_SUN_CNPJ}",
        san_cnpj=THE_SUN_CNPJ,
        ca=(ca_key, ca_cert),
    )
    modern = write_pfx(tmp_path / "modern.pfx", client_key, client_cert)
    legacy = write_pfx(tmp_path / "legacy.pfx", client_key, client_cert, legacy=True)
    ca_file = tmp_path / "client-ca.pem"
    ca_file.write_bytes(ca_cert.public_bytes(serialization.Encoding.PEM))

    server_pem = _pem_files(tmp_path, *_server_certificate(), "server")
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(server_pem)
    context.load_verify_locations(ca_file)
    context.verify_mode = ssl.CERT_REQUIRED

    server = http.server.ThreadingHTTPServer(("localhost", 0), _EchoClientHandler)
    server.socket = context.wrap_socket(server.socket, server_side=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"https://localhost:{server.server_address[1]}", modern, legacy
    server.shutdown()
    server.server_close()


@pytest.mark.parametrize("variant", ["modern", "legacy"])
def test_client_certificate_reencoded(
    browser: Browser, mtls_server: tuple[str, Path, Path], variant: str
) -> None:
    origin, modern, legacy = mtls_server
    pfx = modern if variant == "modern" else legacy
    certificates = build_client_certificates(pfx, PFX_PASSWORD, [origin], reencode=True)
    assert certificates[0]["passphrase"] != PFX_PASSWORD  # real password stays in Python
    context = browser.new_context(client_certificates=certificates, ignore_https_errors=True)
    try:
        page = context.new_page()
        page.goto(origin + "/")
        assert page.locator("#cn").inner_text() == f"THE SUN FULL CONDOMINIUM RESORT:{THE_SUN_CNPJ}"
    finally:
        context.close()


def test_client_certificate_pfx_path(browser: Browser, mtls_server: tuple[str, Path, Path]) -> None:
    origin, modern, _ = mtls_server
    certificates = build_client_certificates(modern, PFX_PASSWORD, [origin], reencode=False)
    context = browser.new_context(client_certificates=certificates, ignore_https_errors=True)
    try:
        page = context.new_page()
        page.goto(origin + "/")
        assert page.locator("#cn").inner_text().endswith(THE_SUN_CNPJ)
    finally:
        context.close()


def test_without_certificate_the_server_refuses(
    browser: Browser, mtls_server: tuple[str, Path, Path]
) -> None:
    origin, _, _ = mtls_server
    context = browser.new_context(ignore_https_errors=True)
    try:
        page = context.new_page()
        with pytest.raises(PlaywrightError, match="ERR_"):
            page.goto(origin + "/")
    finally:
        context.close()


# --- ISSNet session against the fake portal -----------------------------------------------

# Fake ISSNet login, shaped like the real one: #btnAcionaCertificado → ihubauth() opens the
# iHub popup → ticket by postMessage → redirect into the portal.
FAKE_LOGIN = """<html><head><title>ISSNet On-Line</title></head><body>
<a href="#" id="btnAcionaCertificado" onclick="btnAssinar_onClick()">
Logar com certificado digital</a>
<script>
{ihub_script}
function btnAssinar_onClick() {{
  ihubauth(location.search.includes('desafio') ? 'DESAFIO' : 'LICENCA', function (erro, ticket) {{
    if (erro) {{ alert(erro.mensagem); return; }}
    location.href = '/online/Default.aspx?ticket=' + encodeURIComponent(ticket);
  }});
}}
</script></body></html>"""
IHUB_SCRIPT = """
window.ihubauth = function (token, callback) {{
  var base = '{ihub}';
  window.open(base + '/auth?token=' + token, 'ihub_auth_popup');
  window.addEventListener('message', function (event) {{
    if (event.origin !== base) return;
    if (event.data.ok) callback(null, event.data.ticket); else callback(event.data.erro);
  }});
}};"""


def _make_portal_handler(ihub_origin: str) -> type[http.server.BaseHTTPRequestHandler]:
    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            path, _, query = self.path.partition("?")
            if path == "/online/Login/Login.aspx":
                body = FAKE_LOGIN.format(ihub_script=IHUB_SCRIPT.format(ihub=ihub_origin))
            elif path == "/online/Login/SemScripts.aspx":  # scripts blocked (Cloudflare)
                body = FAKE_LOGIN.format(ihub_script="")
            elif path == "/online/Default.aspx":
                ticket = urllib.parse.parse_qs(query).get("ticket", [""])[0]
                body = (
                    "<html><head><title>ISSNet - Principal</title></head><body>"
                    f"<div>Contribuinte: {ticket.replace(':', ' - ')}</div></body></html>"
                )
            else:
                self.send_response(404)
                self.end_headers()
                return
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(body.encode())

        def log_message(self, format: str, *args: object) -> None:
            pass

    return Handler


@pytest.fixture
def fake_portal(mtls_server: tuple[str, Path, Path]) -> Iterator[tuple[str, str, Path]]:
    """Yields (portal origin, iHub origin, legacy pfx accepted by the iHub)."""
    ihub_origin, _, legacy = mtls_server
    server = http.server.ThreadingHTTPServer(("localhost", 0), _make_portal_handler(ihub_origin))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://localhost:{server.server_address[1]}", ihub_origin, legacy
    server.shutdown()
    server.server_close()


def _portal_settings(
    tmp_path: Path, portal: str, ihub: str, pfx: Path, page: str = "Login.aspx"
) -> Settings:
    certs = tmp_path / "certs"
    certs.mkdir(exist_ok=True)
    shutil.copy(pfx, certs / "the-sun.pfx")
    save_password("the-sun.pfx", PFX_PASSWORD)
    return Settings(
        base_dir=tmp_path,
        certs_dir=certs,
        issnet_login_url=f"{portal}/online/Login/{page}?ReturnUrl=%2fonline",
        issnet_cert_origins=[ihub],
        slow_mo_ms=0,
        timeout_ms=5_000,
        navigation_timeout_ms=8_000,
    )


THE_SUN = Condominium(
    active=True,
    name="The Sun Full Condominium Resort",
    cnpj=THE_SUN_CNPJ,
    access_mode=AccessMode.DIRECT,
    certificate="the-sun.pfx",
)


def test_issnet_login_through_ihub_popup(
    browser: Browser, fake_portal: tuple[str, str, Path], tmp_path: Path
) -> None:
    portal, ihub, legacy = fake_portal
    settings = _portal_settings(tmp_path, portal, ihub, legacy)
    context = new_certificate_context(browser, settings, "the-sun.pfx", ignore_https_errors=True)
    try:
        session = IssnetSession(context.new_page(), settings)
        session.login()
        assert "/online/Default.aspx" in session.page.url
        assert len(session.popups) == 1
        check = session.check_identity(THE_SUN)
        assert check.cnpj_found
        assert check.name_found
        assert check.confirmed
        other = THE_SUN.model_copy(update={"cnpj": "11222333000181", "name": "Outro"})
        assert not session.check_identity(other).confirmed
    finally:
        context.close()


def test_issnet_login_with_untrusted_certificate_fails_fast(
    browser: Browser, fake_portal: tuple[str, str, Path], tmp_path: Path
) -> None:
    portal, ihub, _ = fake_portal
    key, cert = make_certificate(f"OUTRA AC:{THE_SUN_CNPJ}")  # not signed by the iHub CA
    pfx = write_pfx(tmp_path / "x.pfx", key, cert)
    settings = _portal_settings(tmp_path, portal, ihub, pfx)
    context = new_certificate_context(browser, settings, "the-sun.pfx", ignore_https_errors=True)
    try:
        session = IssnetSession(context.new_page(), settings)
        started = dt.datetime.now()
        with pytest.raises(LoginError, match="handshake TLS"):
            session.login()
        assert (dt.datetime.now() - started).total_seconds() < 6
    finally:
        context.close()


def test_issnet_login_detects_blocked_scripts(
    browser: Browser, fake_portal: tuple[str, str, Path], tmp_path: Path
) -> None:
    portal, ihub, legacy = fake_portal
    settings = _portal_settings(tmp_path, portal, ihub, legacy, page="SemScripts.aspx")
    context = new_certificate_context(browser, settings, "the-sun.pfx", ignore_https_errors=True)
    try:
        session = IssnetSession(context.new_page(), settings)
        with pytest.raises(LoginError, match="Cloudflare"):
            session.login()
    finally:
        context.close()


def test_missing_password_is_explained(tmp_path: Path, the_sun_pfx: Path) -> None:
    settings = Settings(base_dir=tmp_path, certs_dir=the_sun_pfx.parent)
    with pytest.raises(BrowserSetupError, match="condosys cert add"):
        new_certificate_context(None, settings, "the-sun.pfx")  # type: ignore[arg-type]


# --- recon recorder ------------------------------------------------------------------------

PAGES = {
    "/Login/Login.aspx": "<html><head><title>Login</title></head><body>"
    "<a id='go' href='/Home.aspx'>Logar com certificado digital</a></body></html>",
    "/Home.aspx": "<html><head><title>Home</title></head><body><p>12.166.128/0001-09</p>"
    "<iframe src='/Frame.aspx'></iframe></body></html>",
    "/Frame.aspx": "<html><body><p id='inside'>frame</p></body></html>",
}


class _PagesHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        body = PAGES.get(self.path.split("?")[0])
        self.send_response(200 if body else 404)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write((body or "not found").encode())

    def log_message(self, format: str, *args: object) -> None:
        pass


@pytest.fixture
def pages_server() -> Iterator[str]:
    server = http.server.ThreadingHTTPServer(("localhost", 0), _PagesHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://localhost:{server.server_address[1]}"
    server.shutdown()
    server.server_close()


def test_recorder_captures_loads_button_and_requests(
    browser: Browser, pages_server: str, tmp_path: Path
) -> None:
    out = tmp_path / "recon"
    recorder = PageRecorder(out)
    context = browser.new_context()
    try:
        recorder.attach(context)
        page = context.new_page()

        def wait_captures(count: int) -> None:
            # Load captures run in event handlers, concurrently with the test.
            for _ in range(50):
                if len(recorder.captures) >= count:
                    return
                page.wait_for_timeout(100)
            raise AssertionError(f"expected {count} captures, got {recorder.captures}")

        page.goto(pages_server + "/Login/Login.aspx")
        wait_captures(1)
        page.click("#go")
        page.wait_for_url("**/Home.aspx")
        wait_captures(2)
        page.locator("condosys-recon button").click()
        wait_captures(3)
        recorder.flush()
    finally:
        context.close()

    entries = [json.loads(line) for line in (out / "index.jsonl").read_text().splitlines()]
    kinds = [(entry["kind"], entry["title"]) for entry in entries]
    assert ("load", "Login") in kinds
    assert ("load", "Home") in kinds
    assert ("manual", "Home") in kinds

    home = next(e for e in entries if e["kind"] == "load" and e["title"] == "Home")
    assert any(name.endswith(".frame1.html") for name in home["files"])
    assert all((out / name).is_file() for entry in entries for name in entry["files"])

    manual = next(e for e in entries if e["kind"] == "manual")
    html = (out / manual["files"][0]).read_text(encoding="utf-8")
    assert "12.166.128/0001-09" in html
    assert "condosys-recon" not in html  # injected button is stripped
    assert (out / manual["files"][0].replace(".html", ".png")).is_file()

    requests_log = (out / "requests.log").read_text(encoding="utf-8")
    assert "/Login/Login.aspx" in requests_log
    assert "Cookie" not in requests_log


def test_issnet_login_explains_wrong_certificate_origin(
    browser: Browser, fake_portal: tuple[str, str, Path], tmp_path: Path
) -> None:
    portal, ihub, legacy = fake_portal
    settings = _portal_settings(tmp_path, portal, ihub, legacy)
    # Certificate configured for another origin, as an outdated .env would do.
    settings = settings.model_copy(update={"issnet_cert_origins": ["https://iss.example"]})
    context = new_certificate_context(browser, settings, "the-sun.pfx", ignore_https_errors=True)
    try:
        session = IssnetSession(context.new_page(), settings)
        with pytest.raises(LoginError, match=f"o popup de autenticação abriu em {ihub}"):
            session.login()
    finally:
        context.close()


def test_issnet_login_waits_for_human_check(
    browser: Browser,
    fake_portal: tuple[str, str, Path],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    portal, ihub, legacy = fake_portal
    monkeypatch.setattr(selectors, "HUMAN_CHECK_FRAME_URL", f"{ihub}/turnstile")
    settings = _portal_settings(tmp_path, portal, ihub, legacy).model_copy(
        update={
            "issnet_login_url": f"{portal}/online/Login/Login.aspx?desafio=1",
            # Shorter than the fake challenge (2.5 s): only the extension lets it pass.
            "navigation_timeout_ms": 1_000,
            "human_check_timeout_ms": 10_000,
        }
    )
    context = new_certificate_context(browser, settings, "the-sun.pfx", ignore_https_errors=True)
    try:
        session = IssnetSession(context.new_page(), settings)
        with caplog.at_level("WARNING", logger="condosys"):
            session.login()
        assert session.human_check_shown
        assert "Confirme que é humano" in caplog.text
        assert session.check_identity(THE_SUN).confirmed
    finally:
        context.close()
