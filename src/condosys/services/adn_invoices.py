"""Taken invoices of a condominium from the ADN store (direct access)."""

import logging
from collections.abc import Iterable

from condosys.adn import StoredDocument
from condosys.models import Competence, InvoiceDetail
from condosys.nfse_nacional import NfseParseError, parse_nfse_xml

logger = logging.getLogger(__name__)

NFSE_KIND = "NFSE"


def taken_invoices(
    documents: Iterable[StoredDocument], taker_cnpj: str, competence: Competence
) -> list[InvoiceDetail]:
    """NFS-e where ``taker_cnpj`` is the taker, issued within the competence month.

    Like the manual routine (issue date from the first to the last day of the month).
    Events and other document kinds are skipped; unreadable XML is logged and skipped.

    Returns:
        Invoices sorted by issue date and number.
    """
    found: list[InvoiceDetail] = []
    for document in documents:
        if document.kind != NFSE_KIND:
            continue
        try:
            invoice = parse_nfse_xml(document.xml, access_key=document.access_key)
        except NfseParseError as exc:
            logger.warning("NSU %s ignorado: %s", document.nsu, exc)
            continue
        if invoice.taker_document != taker_cnpj:
            continue
        if competence.first_day <= invoice.issue_date <= competence.last_day:
            found.append(invoice)
    return sorted(found, key=lambda invoice: (invoice.issue_date, invoice.number))
