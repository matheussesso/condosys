"""Page Object for "Consulta de Notas Tomadas". Navigates and returns raw HTML only.

``open`` works with provisional locators (visible menu texts); the query itself is
implemented in phase 2, once ``selectors.py`` is filled from the recon material.
"""

import logging
from datetime import datetime
from pathlib import Path

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import Locator, Page

from condosys.models import Competence
from condosys.portals.issnet import selectors
from condosys.portals.issnet.session import NavigationError, save_page_snapshot

logger = logging.getLogger(__name__)


class TakenInvoicesPage:
    """Menu → Declaração de Serviços Contratados → Consulta de Notas Tomadas."""

    def __init__(self, page: Page, debug_dir: Path | None = None) -> None:
        self.page = page
        self.debug_dir = debug_dir

    def open(self) -> None:
        """Navigates to the query screen through the portal menu.

        Raises:
            NavigationError: If a menu item is not found (the screen is saved to debug/).
        """
        page = self.page
        try:
            if selectors.TAKEN_INVOICES_URL is not None:
                page.goto(selectors.TAKEN_INVOICES_URL)
            else:
                # PROVISÓRIO: visible menu texts until the recon gives the real ids.
                if not self._menu_item(selectors.MENU_CONTRACTED_SERVICES_TEXT).is_visible():
                    self._clickable(selectors.MENU_TEXT).click()
                self._menu_item(selectors.MENU_CONTRACTED_SERVICES_TEXT).click()
                self._menu_item(selectors.MENU_TAKEN_INVOICES_TEXT).click()
            page.wait_for_load_state("load")
            page.get_by_text(selectors.TAKEN_INVOICES_PAGE_TEXT).first.wait_for()
        except PlaywrightError as exc:
            raise self._error(str(exc).splitlines()[0]) from exc
        logger.info("Tela Consulta de Notas Tomadas aberta: %s", page.url.split("?")[0])

    def _clickable(self, text: str) -> Locator:
        return (
            self.page.get_by_role("button", name=text, exact=True)
            .or_(self.page.get_by_role("link", name=text, exact=True))
            .first
        )

    def _menu_item(self, text: str) -> Locator:
        return self.page.get_by_text(text, exact=True).first

    def _error(self, message: str) -> NavigationError:
        where = ""
        if self.debug_dir is not None:
            saved = save_page_snapshot(
                self.page, self.debug_dir, f"falha-menu_{datetime.now():%Y%m%d-%H%M%S}"
            )
            if saved:
                where = f" Tela salva em {saved[0].parent}/{saved[0].stem}.*"
        return NavigationError(
            f"não foi possível abrir Consulta de Notas Tomadas: {message.rstrip('.')}.{where}"
        )

    def search(self, competence: Competence) -> None:
        """Fills the filters (NFS-e, first/last day of the competence, status Normal).

        Then clicks "Localizar".
        """
        # TODO(fase 2): fill selectors.FILTER_* and click FILTER_SEARCH_BUTTON.
        raise NotImplementedError("Fase 2: filtros dependem dos seletores capturados no recon.")

    def result_pages_html(self) -> list[str]:
        """Returns the HTML of every grid page, following the pager."""
        # TODO(fase 2): iterate RESULTS_PAGER_NEXT, pausing between pages.
        raise NotImplementedError("Fase 2: paginação depende dos seletores capturados no recon.")

    def invoice_html(self, row_index: int) -> str:
        """Opens an invoice ("Visualizar") and returns its HTML."""
        # TODO(fase 3): ROW_VIEW_BUTTON may open a popup; handle with context.expect_page().
        raise NotImplementedError("Fase 3: detalhe da nota depende do recon.")

    def invoice_xml(self, row_index: int) -> str | None:
        """Downloads the invoice XML, if the row document icon provides it."""
        # TODO(fase 3): check ROW_DOCUMENT_BUTTON with page.expect_download().
        raise NotImplementedError("Fase 3: download do XML depende do recon.")
