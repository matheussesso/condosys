"""ISSNet session: certificate login, taxpayer selection (proxy access), checks, logout.

Navigation only — no parsing of business data here.

Login flow (confirmed on the public login page, see ``docs/issnet-mapa.md``): the
"Logar com certificado digital" button opens a popup at ``https://api.ihub.com.br/auth``.
That server asks for the client certificate in the TLS handshake — which Playwright
answers through ``client_certificates`` — and posts a ticket back to the login page, which
submits it and redirects into the portal.
"""

import contextlib
import logging
import re
import time
import unicodedata
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

from playwright.sync_api import BrowserContext, Dialog, Page, Request
from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from condosys.assisted_browser import assisted_browser
from condosys.browser import launch_browser, new_certificate_context
from condosys.models import AccessMode, Condominium
from condosys.portals.issnet import selectors
from condosys.settings import Settings

logger = logging.getLogger(__name__)

PLAN_B_HINT = "Veja o 'Plano B' em docs/decisoes.md."
_CERT_ERROR_MARKERS = ("ERR_BAD_SSL_CLIENT_AUTH_CERT", "ERR_SSL_CLIENT_AUTH", "ERR_SSL_PROTOCOL")
# When the TLS handshake with the certificate fails, Playwright serves an HTML page with
# this text (HTTP 503) instead of raising.
PLAYWRIGHT_CERT_ERROR_TEXT = "Playwright client-certificate error"


class LoginError(RuntimeError):
    """Raised when the certificate login does not succeed."""


class ManualStepRequired(RuntimeError):  # noqa: N818 - it is a signal, not a failure
    """Raised when a step has no captured selector yet and must be done by hand."""


@dataclass(frozen=True)
class IdentityCheck:
    """Whether the page shows the expected condominium."""

    cnpj_found: bool
    name_found: bool
    source: str

    @property
    def confirmed(self) -> bool:
        """The CNPJ is the reliable proof; the name alone is only a hint."""
        return self.cnpj_found


def _plain(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text)
    return " ".join("".join(c for c in decomposed if not unicodedata.combining(c)).upper().split())


def _origin(url: str) -> str:
    parts = urlsplit(url)
    return f"{parts.scheme}://{parts.netloc}"


def _without_query(url: str) -> str:
    # Query strings may carry tokens (e.g. the iHub license); never print them.
    parts = urlsplit(url)
    return f"{parts.scheme}://{parts.netloc}{parts.path}"


class IssnetSession:
    """Page Object for the authenticated ISSNet environment."""

    def __init__(self, page: Page, settings: Settings, *, assisted: bool = False) -> None:
        self.page = page
        self.settings = settings
        # Assisted mode: a person already logged in on this page (see assisted_browser).
        self.assisted = assisted
        self.popups: list[Page] = []
        self.popup_origins: list[str] = []
        self.human_check_shown = False
        self.dialog_messages: list[str] = []
        self._failed_documents: list[tuple[str, str]] = []
        # Context-level, so popup requests are seen from the very first one.
        page.context.on("request", self._on_request)
        page.context.on("requestfailed", self._on_request_failed)
        page.on("popup", self._on_popup)
        page.on("dialog", self._on_dialog)

    def _on_request_failed(self, request: Request) -> None:
        if request.resource_type == "document":
            self._failed_documents.append((request.url, request.failure or "?"))

    def _on_popup(self, popup: Page) -> None:
        logger.info("Popup aberto: %s", _without_query(popup.url))
        self.popups.append(popup)

    def _on_request(self, request: Request) -> None:
        # Documents outside the portal origin are the authentication popup. Kept at request
        # time: after a TLS failure the popup URL becomes chrome-error://. (request.frame is
        # not usable here: it does not exist yet for a popup's first navigation.)
        if request.resource_type != "document":
            return
        origin = _origin(request.url)
        portal = _origin(self.settings.issnet_login_url)
        if origin.startswith("https://") and origin != portal and origin not in self.popup_origins:
            self.popup_origins.append(origin)

    def _on_dialog(self, dialog: Dialog) -> None:
        # The login page reports iHub errors with alert(); keep the text and close it.
        self.dialog_messages.append(dialog.message)
        logger.warning("Alerta do portal: %s", dialog.message)
        with contextlib.suppress(PlaywrightError):
            dialog.dismiss()

    # --- login -----------------------------------------------------------------------

    def login(self) -> None:
        """Opens the login page and logs in with the context's client certificate.

        In assisted mode the person has already logged in; this only checks it.

        Raises:
            LoginError: If the portal rejects the certificate or the login does not finish.
        """
        if self.assisted:
            if not self._is_logged_in_url(self.page.url):
                raise LoginError(
                    f"a aba do navegador não está dentro do portal: {_without_query(self.page.url)}"
                )
            logger.info("Sessão assumida: %s", _without_query(self.page.url))
            return
        logger.info("Abrindo %s", _without_query(self.settings.issnet_login_url))
        try:
            response = self.page.goto(self.settings.issnet_login_url, wait_until="load")
        except PlaywrightError as exc:
            raise self._login_error("não foi possível abrir a página de login", exc) from exc
        # Checked first: Playwright serves its certificate error page with HTTP 503.
        self._raise_on_certificate_error_page(self.page)
        if response is not None and response.status >= 400:
            raise LoginError(f"a página de login respondeu HTTP {response.status}. {PLAN_B_HINT}")
        self._ensure_login_scripts()

        try:
            self.page.locator(selectors.LOGIN_CERTIFICATE_BUTTON).click()
            self._wait_for_login()
            self.page.wait_for_load_state("load")
        except PlaywrightTimeoutError as exc:
            message = "o login não foi concluído no tempo limite"
            if self.human_check_shown:
                message += " (a verificação 'Confirme que é humano' do iHub não foi concluída)"
            raise self._login_error(message, exc) from exc
        except PlaywrightError as exc:
            raise self._login_error("o portal recusou a conexão com certificado", exc) from exc
        self._raise_on_certificate_error_page(self.page)
        logger.info("Login concluído: %s", _without_query(self.page.url))

    def _wait_for_login(self) -> None:
        """Waits for the redirect into the portal, failing fast on popup/alert errors.

        While the iHub popup shows the "Confirme que é humano" check, a person must tick it:
        the user is told so and the deadline is extended by ``human_check_timeout_ms``.
        """
        deadline = time.monotonic() + self.settings.navigation_timeout_ms / 1000
        human_check_seen = False
        while not self._is_logged_in_url(self.page.url):
            for popup in self.popups:
                if popup.is_closed():
                    continue
                self._raise_on_certificate_error_page(popup)
                if not human_check_seen and self._has_human_check(popup):
                    human_check_seen = True
                    self.human_check_shown = True
                    deadline = max(
                        deadline,
                        time.monotonic() + self.settings.human_check_timeout_ms / 1000,
                    )
                    logger.warning(
                        "Verificação humana na janela do iHub: marque 'Confirme que é humano' "
                        "(aguardando até %d s).",
                        self.settings.human_check_timeout_ms // 1000,
                    )
            if self.dialog_messages:
                raise self._login_error(
                    "o portal recusou o login", PlaywrightError(self.dialog_messages[-1])
                )
            if time.monotonic() > deadline:
                raise PlaywrightTimeoutError("tempo esgotado aguardando a entrada no portal")
            self.page.wait_for_timeout(250)

    @staticmethod
    def _has_human_check(popup: Page) -> bool:
        try:
            return any(selectors.HUMAN_CHECK_FRAME_URL in frame.url for frame in popup.frames)
        except PlaywrightError:
            return False

    def _ensure_login_scripts(self) -> None:
        function = selectors.LOGIN_AUTH_FUNCTION
        try:
            loaded = self.page.evaluate(f"typeof window.{function} === 'function'")
        except PlaywrightError:
            loaded = True  # cannot tell; let the click report the real problem
        if not loaded:
            raise LoginError(
                "os scripts de login do portal não carregaram (o Cloudflare bloqueia o "
                "navegador em modo invisível). Rode com a janela visível "
                "(CONDOSYS_HEADLESS=false, sem --headless)."
            )

    def _is_logged_in_url(self, url: str) -> bool:
        if selectors.LOGGED_IN_URL_PATTERN is not None:
            return re.search(selectors.LOGGED_IN_URL_PATTERN, url) is not None
        # TODO: capturar via recon — until then, "left the /Login/ area without an error
        # page" (after login the portal goes to /online/default/..., e.g. empresas.aspx).
        path = urlsplit(url).path.lower()
        return "/login/" not in path and not url.startswith("chrome-error:")

    def _raise_on_certificate_error_page(self, page: Page) -> None:
        text = self._certificate_error_text(page)
        if text is not None:
            raise LoginError(
                f"o handshake TLS com o certificado falhou em {_origin(page.url)}: {text}\n"
                f"{PLAN_B_HINT}"
            )

    @staticmethod
    def _certificate_error_text(page: Page) -> str | None:
        try:
            body = page.locator("body").inner_text(timeout=3_000)
        except PlaywrightError:
            return None
        if PLAYWRIGHT_CERT_ERROR_TEXT in body:
            return body.strip()[:400]
        return None

    def _login_error(self, message: str, exc: Exception) -> LoginError:
        details = [message]
        for origin in self.popup_origins:
            if origin not in self.settings.issnet_cert_origins:
                details.append(
                    f"o popup de autenticação abriu em {origin}, mas o certificado só é enviado "
                    f"para {', '.join(self.settings.issnet_cert_origins)}: ajuste "
                    f'CONDOSYS_ISSNET_CERT_ORIGINS=["{origin}"] no .env'
                )
        for popup in self.popups:
            if popup.is_closed():
                continue
            text = self._certificate_error_text(popup)
            if text is not None:
                details.append(f"handshake TLS com o certificado falhou no popup: {text}")
            else:
                details.append(f"popup ainda aberto em {_without_query(popup.url)}")
        for url, failure in self._failed_documents:
            details.append(f"falha em {_without_query(url)}: {failure}")
            origin = _origin(url)
            if (
                any(marker in failure for marker in _CERT_ERROR_MARKERS)
                and origin not in self.settings.issnet_cert_origins
            ):
                details.append(
                    f"o certificado não foi enviado para {origin}: inclua essa origem em "
                    "CONDOSYS_ISSNET_CERT_ORIGINS no .env"
                )
        details.extend(f"alerta do portal: {text}" for text in self.dialog_messages)
        page_error = self._visible_login_error()
        if page_error:
            details.append(f"mensagem do portal: {page_error}")
        details.append(f"URL atual: {_without_query(self.page.url)}")
        details.append(f"erro do navegador: {str(exc).splitlines()[0]}")
        details.append(PLAN_B_HINT)
        return LoginError("\n".join(details))

    def _visible_login_error(self) -> str | None:
        if selectors.LOGIN_ERROR_MESSAGE is None:
            return None
        try:
            locator = self.page.locator(selectors.LOGIN_ERROR_MESSAGE).first
            return locator.inner_text(timeout=2_000).strip() or None
        except PlaywrightError:
            return None

    # --- taxpayer (proxy access) -------------------------------------------------------

    def select_taxpayer(self, condominium: Condominium) -> None:
        """Selects the condominium in the header taxpayer selector (proxy access).

        Raises:
            ManualStepRequired: While the selector has not been captured by the recon.
        """
        if selectors.TAXPAYER_SELECTOR is None:
            # TODO: capturar via recon — the selector next to the competence in the header.
            raise ManualStepRequired(
                f"selecione o contribuinte {condominium.name} ({condominium.cnpj_formatted}) "
                "no cabeçalho do portal"
            )
        raise NotImplementedError("Implementar após capturar TAXPAYER_SELECTOR no recon.")

    # --- checks ------------------------------------------------------------------------

    def identity_text(self) -> tuple[str, str]:
        """Returns (text, source) used to identify the current taxpayer."""
        if selectors.HEADER_TAXPAYER is not None:
            locator = self.page.locator(selectors.HEADER_TAXPAYER).first
            return locator.inner_text(), "cabeçalho"
        # TODO: capturar via recon — until then, search the text of every frame.
        texts = []
        for frame in self.page.frames:
            try:
                texts.append(frame.locator("body").inner_text(timeout=5_000))
            except PlaywrightError:
                continue
        return "\n".join(texts), "texto da página"

    def check_identity(self, condominium: Condominium) -> IdentityCheck:
        """Checks that the page shows the condominium CNPJ (and name)."""
        text, source = self.identity_text()
        compact = re.sub(r"[.\-/\s]", "", text).upper()
        return IdentityCheck(
            cnpj_found=condominium.cnpj in compact,
            name_found=_plain(condominium.name) in _plain(text),
            source=source,
        )

    # --- utilities ---------------------------------------------------------------------

    def screenshot(self, path: Path) -> Path:
        """Saves a full-page screenshot."""
        path.parent.mkdir(parents=True, exist_ok=True)
        self.page.screenshot(path=path, full_page=True)
        return path

    def logout(self) -> None:
        """Logs out, when the logout selector is known (closing the context also ends it)."""
        if selectors.LOGOUT_BUTTON is None:
            # TODO: capturar via recon. Closing the context discards the session anyway.
            return
        try:
            self.page.locator(selectors.LOGOUT_BUTTON).first.click()
        except PlaywrightError:
            logger.warning("Não foi possível sair do portal; o contexto será fechado.")


@contextmanager
def issnet_session(
    settings: Settings,
    condominium: Condominium,
    *,
    headless: bool | None = None,
    on_context: Callable[[BrowserContext], None] | None = None,
) -> Iterator[IssnetSession]:
    """Opens a browser with the condominium certificate and yields a session (not logged in).

    Args:
        settings: Application settings.
        condominium: Condominium whose certificate (direct or proxy) is used.
        headless: Overrides ``settings.headless``.
        on_context: Called with the new context before any page opens (e.g. recorders).

    Yields:
        The session; call ``login()`` next. In assisted mode (``settings.login_mode``) the
        person logs in on the regular Chrome/Edge before this yields.
    """
    if settings.login_mode == "assisted":
        with assisted_browser(settings, settings.issnet_login_url) as browser:
            context = browser.contexts[0]
            if on_context is not None:
                on_context(context)
            pages = [
                p for p in context.pages if _origin(p.url) == _origin(settings.issnet_login_url)
            ]
            page = pages[-1] if pages else context.pages[-1]
            context.set_default_timeout(settings.timeout_ms)
            context.set_default_navigation_timeout(settings.navigation_timeout_ms)
            yield IssnetSession(page, settings, assisted=True)
        return

    with launch_browser(settings, headless=headless) as browser:
        context = new_certificate_context(browser, settings, condominium.certificate)
        try:
            if on_context is not None:
                on_context(context)
            session = IssnetSession(context.new_page(), settings)
            yield session
            session.logout()
        finally:
            context.close()


def needs_taxpayer_selection(condominium: Condominium) -> bool:
    """Proxy access lists several taxpayers after login."""
    return condominium.access_mode is AccessMode.PROXY
