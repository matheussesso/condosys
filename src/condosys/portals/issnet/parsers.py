"""Pure parsing functions: HTML/XML in, Pydantic models out. No browser access here.

Implemented in phases 2 and 3, tested with fixtures saved from ``condosys recon`` in
``tests/fixtures/``.
"""

from condosys.models import Invoice, InvoiceDetail


def parse_invoice_grid(html: str) -> list[Invoice]:
    """Parses the "Documentos Fiscais" grid of "Consulta Notas Tomadas".

    Args:
        html: HTML of one grid page.

    Returns:
        One ``Invoice`` per grid row.
    """
    # TODO(fase 2): implement with the grid HTML captured via recon.
    raise NotImplementedError("Fase 2: parsing da grade depende do HTML real (recon).")


def has_next_page(html: str) -> bool:
    """Whether the grid page has a "next page" link."""
    # TODO(fase 2): implement with the pager HTML captured via recon.
    raise NotImplementedError("Fase 2: paginação depende do HTML real (recon).")


def parse_invoice_detail_html(html: str) -> InvoiceDetail:
    """Parses an invoice opened with "Visualizar"."""
    # TODO(fase 3): implement with the invoice HTML captured via recon.
    raise NotImplementedError("Fase 3: parsing da nota depende do HTML real (recon).")


def parse_invoice_detail_xml(xml: str) -> InvoiceDetail:
    """Parses the NFS-e XML (preferred over HTML when available)."""
    # TODO(fase 3): check whether the row document icon downloads the XML and its layout.
    raise NotImplementedError("Fase 3: parsing do XML depende do arquivo real (recon).")
