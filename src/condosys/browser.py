"""Browser factory: one fresh ``BrowserContext`` per certificate.

Authentication uses Playwright's native ``client_certificates`` (Playwright >= 1.47): the
browser presents the ``.pfx`` during the TLS handshake with the configured origins, with
no certificate picker. A new context per certificate means no cookie, cache or TLS
session leaks between condominiums.
"""

import logging
import secrets
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING

from playwright.sync_api import Browser, BrowserContext, sync_playwright
from playwright.sync_api import Error as PlaywrightError

from condosys.certificates import CertificateError, load_pfx, reencode_pfx
from condosys.credentials import get_password
from condosys.settings import Settings

if TYPE_CHECKING:
    from playwright._impl._api_structures import ClientCertificate

logger = logging.getLogger(__name__)


class BrowserSetupError(RuntimeError):
    """Raised when the browser or the certificate cannot be prepared."""


@contextmanager
def launch_browser(settings: Settings, *, headless: bool | None = None) -> Iterator[Browser]:
    """Starts Playwright and launches Chromium (or the configured Edge/Chrome channel).

    Args:
        settings: Application settings.
        headless: Overrides ``settings.headless``.

    Yields:
        The running browser; it is closed on exit.

    Raises:
        BrowserSetupError: If the browser is not installed or fails to start.
    """
    channel = None if settings.browser_channel == "chromium" else settings.browser_channel
    with sync_playwright() as playwright:
        try:
            browser = playwright.chromium.launch(
                headless=settings.headless if headless is None else headless,
                channel=channel,
                slow_mo=settings.slow_mo_ms,
            )
        except PlaywrightError as exc:
            hint = (
                "rode: uv run playwright install chromium"
                if channel is None
                else f"verifique se o navegador '{channel}' está instalado"
            )
            raise BrowserSetupError(f"não foi possível abrir o navegador ({hint}).\n{exc}") from exc
        logger.debug("Navegador iniciado: %s %s", settings.browser_channel, browser.version)
        try:
            yield browser
        finally:
            browser.close()


def build_client_certificates(
    certificate_path: Path,
    password: str,
    origins: Sequence[str],
    *,
    reencode: bool = True,
) -> "list[ClientCertificate]":
    """Builds the ``client_certificates`` argument for ``browser.new_context``.

    With ``reencode`` the ``.pfx`` is re-serialized in memory with AES-256 and a random,
    single-use passphrase, so legacy RC2/3DES files work and the real password never
    leaves this process.

    Args:
        certificate_path: The ``.pfx`` file.
        password: Its password.
        origins: Origins (``https://host[:port]``) that should receive the certificate.
        reencode: Re-encode the PKCS#12 in memory (recommended).

    Returns:
        One entry per origin.

    Raises:
        BrowserSetupError: If the certificate cannot be opened.
    """
    if not origins:
        raise BrowserSetupError("nenhuma origem configurada para o certificado")
    try:
        loaded = load_pfx(certificate_path, password)
    except CertificateError as exc:
        raise BrowserSetupError(str(exc)) from exc

    if not reencode:
        return [
            {"origin": origin, "pfxPath": certificate_path, "passphrase": password}
            for origin in origins
        ]
    passphrase = secrets.token_urlsafe(24)
    blob = reencode_pfx(loaded, passphrase)
    return [{"origin": origin, "pfx": blob, "passphrase": passphrase} for origin in origins]


def stored_password(certificate_file: str) -> str:
    """Reads a certificate password from the keyring.

    Raises:
        BrowserSetupError: If no password is stored for the file.
    """
    password = get_password(certificate_file)
    if password is None:
        raise BrowserSetupError(
            f"senha do certificado {certificate_file} não cadastrada. "
            f"Rode: uv run condosys cert add certs/{certificate_file}"
        )
    return password


def new_certificate_context(
    browser: Browser,
    settings: Settings,
    certificate_file: str,
    *,
    record_video_dir: Path | None = None,
    ignore_https_errors: bool = False,
) -> BrowserContext:
    """Creates an isolated context that authenticates with one certificate.

    Args:
        browser: Running browser.
        settings: Application settings (origins, timeouts, re-encoding).
        certificate_file: File name inside ``settings.certs_dir``.
        record_video_dir: Optional directory for Playwright videos.
        ignore_https_errors: Accept invalid server certificates. Tests only (local servers).

    Returns:
        The new context, with default timeouts applied.

    Raises:
        BrowserSetupError: If the certificate or its password is missing or invalid.
    """
    certificate_path = settings.certs_dir / certificate_file
    if not certificate_path.is_file():
        raise BrowserSetupError(f"certificado não encontrado: {certificate_path}")
    certificates = build_client_certificates(
        certificate_path,
        stored_password(certificate_file),
        settings.issnet_cert_origins,
        reencode=settings.reencode_pfx,
    )
    context = browser.new_context(
        client_certificates=certificates,
        locale="pt-BR",
        timezone_id="America/Sao_Paulo",
        viewport={"width": 1366, "height": 900},
        accept_downloads=True,
        record_video_dir=record_video_dir,
        ignore_https_errors=ignore_https_errors,
    )
    context.set_default_timeout(settings.timeout_ms)
    context.set_default_navigation_timeout(settings.navigation_timeout_ms)
    logger.info(
        "Contexto criado com o certificado %s para %s",
        certificate_file,
        ", ".join(settings.issnet_cert_origins),
    )
    return context
