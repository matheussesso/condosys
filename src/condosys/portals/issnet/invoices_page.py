"""Page Object for "Consulta de Notas Tomadas". Navigates and returns raw HTML only.

Implemented in phase 2, once ``selectors.py`` is filled from the recon material.
"""

from playwright.sync_api import Page

from condosys.models import Competence


class TakenInvoicesPage:
    """Menu → Declaração de Serviços Contratados → Consulta de Notas Tomadas."""

    def __init__(self, page: Page) -> None:
        self.page = page

    def open(self) -> None:
        """Navigates to the query screen."""
        # TODO(fase 2): use selectors.MENU_* or selectors.TAKEN_INVOICES_URL.
        raise NotImplementedError("Fase 2: navegação depende dos seletores capturados no recon.")

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
