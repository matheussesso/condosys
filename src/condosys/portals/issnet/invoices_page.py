"""Page Object for "Consulta de Notas Tomadas". Navigates and returns raw HTML only.

``open`` loads the screen in the shell content iframe (address confirmed from the real
menu); the query itself is implemented in phase 2, once the recon captures the screen.
"""

import logging
from datetime import datetime
from pathlib import Path
from urllib.parse import urljoin

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import Frame, Page

from condosys.models import Competence
from condosys.portals.issnet import selectors
from condosys.portals.issnet.session import NavigationError, save_page_snapshot

logger = logging.getLogger(__name__)


class TakenInvoicesPage:
    """Menu → Declaração de Serviços Contratados → Consulta de Notas Tomadas."""

    def __init__(self, page: Page, debug_dir: Path | None = None) -> None:
        self.page = page
        self.debug_dir = debug_dir
        # Where the screen lives: the shell content iframe, or the page itself.
        self.frame: Frame = page.main_frame

    def open(self) -> None:
        """Opens the query screen in the content iframe, as the menu link does.

        Raises:
            NavigationError: If the screen does not open (it is saved to debug/).
        """
        page = self.page
        url = urljoin(page.url, selectors.TAKEN_INVOICES_PATH)
        try:
            frame = page.frame(name=selectors.CONTENT_FRAME_NAME)
            if frame is not None:
                frame.goto(url, wait_until="domcontentloaded")
                self.frame = frame
            else:
                page.goto(url, wait_until="domcontentloaded")
                self.frame = page.main_frame
            self.frame.get_by_text(selectors.TAKEN_INVOICES_PAGE_TEXT).first.wait_for()
        except PlaywrightError as exc:
            raise self._error(str(exc).splitlines()[0]) from exc
        logger.info("Tela Consulta de Notas Tomadas aberta: %s", url)

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
