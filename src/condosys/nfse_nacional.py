"""Parsing of the national NFS-e XML (layout "NFSe" 1.00, namespace sped.fazenda.gov.br).

Pure functions: XML in, ``InvoiceDetail`` out. Field mapping in ``docs/adn.md``. Codes
whose meaning is still to be confirmed against the national layout are marked there.
"""

from datetime import date
from decimal import Decimal
from xml.etree import ElementTree as ET

from condosys.models import InvoiceDetail

NAMESPACE = "http://www.sped.fazenda.gov.br/nfse"
_NS = {"n": NAMESPACE}
# tpRetISSQN: 1 = not withheld, 2 = withheld by the taker, 3 = by the intermediary.
ISS_WITHHELD_CODES = {"2", "3"}


class NfseParseError(ValueError):
    """Raised when the XML is not a national NFS-e."""


def _text(node: ET.Element, path: str) -> str | None:
    found = node.find(path, _NS)
    if found is None or found.text is None:
        return None
    return found.text.strip()


def _money(node: ET.Element, path: str) -> Decimal:
    value = _text(node, path)
    return Decimal(value) if value else Decimal("0")


def _document(node: ET.Element, prefix: str) -> str:
    return _text(node, f"{prefix}/n:CNPJ") or _text(node, f"{prefix}/n:CPF") or ""


def parse_nfse_xml(xml: str, access_key: str | None = None) -> InvoiceDetail:
    """Parses one national NFS-e.

    Args:
        xml: The ``<NFSe>`` document.
        access_key: ``ChaveAcesso`` from the ADN batch; read from ``infNFSe/@Id`` if omitted.

    Returns:
        The invoice.

    Raises:
        NfseParseError: If the XML is malformed or lacks the required fields.
    """
    try:
        root = ET.fromstring(xml)
    except ET.ParseError as exc:
        raise NfseParseError(f"XML inválido: {exc}") from exc
    inf = root.find("n:infNFSe", _NS)
    if root.tag != f"{{{NAMESPACE}}}NFSe" or inf is None:
        raise NfseParseError("não é uma NFS-e do padrão nacional")
    dps = inf.find("n:DPS/n:infDPS", _NS)
    if dps is None:
        raise NfseParseError("NFS-e sem DPS")

    number = _text(inf, "n:nNFSe")
    issued = _text(dps, "n:dhEmi")
    if not number or not issued:
        raise NfseParseError("NFS-e sem número ou data de emissão")
    competence = _text(dps, "n:dCompet")

    iss_amount = _money(inf, "n:valores/n:vISSQN")
    iss_withheld = _text(dps, "n:valores/n:trib/n:tribMun/n:tpRetISSQN") in ISS_WITHHELD_CODES
    federal = "n:valores/n:trib/n:tribFed"
    location_name = _text(inf, "n:xLocPrestacao")
    location_code = _text(dps, "n:serv/n:locPrest/n:cLocPrestacao")

    key = access_key or (inf.get("Id") or "").removeprefix("NFS") or None
    return InvoiceDetail(
        number=number,
        issue_date=date.fromisoformat(issued[:10]),
        amount=_money(dps, "n:valores/n:vServPrest/n:vServ"),
        iss_amount=iss_amount,
        tax_withheld=iss_withheld,
        provider_document=_document(inf, "n:emit"),
        provider_name=_text(inf, "n:emit/n:xNome") or "",
        status=_text(inf, "n:cStat") or "",
        version=root.get("versao", ""),
        service_code=_text(dps, "n:serv/n:cServ/n:cTribNac"),
        service_description=_text(dps, "n:serv/n:cServ/n:xDescServ") or "",
        service_location=" - ".join(p for p in (location_code, location_name) if p),
        pis=_money(dps, f"{federal}/n:piscofins/n:vPis"),
        cofins=_money(dps, f"{federal}/n:piscofins/n:vCofins"),
        csll=_money(dps, f"{federal}/n:vRetCSLL"),
        # NT 07: withheld PIS/COFINS are added to the CSLL field (docs/adn.md).
        social_contributions_withheld=_money(dps, f"{federal}/n:vRetCSLL"),
        inss=_money(dps, f"{federal}/n:vRetCP"),
        irrf=_money(dps, f"{federal}/n:vRetIRRF"),
        iss_withheld=iss_amount if iss_withheld else Decimal("0"),
        deductions=_money(dps, "n:valores/n:vDedRed/n:vDR"),
        net_amount=_money(inf, "n:valores/n:vLiq"),
        taker_document=_document(dps, "n:toma"),
        taker_name=_text(dps, "n:toma/n:xNome") or "",
        raw_source="xml",
        access_key=key,
        competence_date=date.fromisoformat(competence) if competence else None,
    )
