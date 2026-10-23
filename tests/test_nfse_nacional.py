from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from condosys.nfse_nacional import NfseParseError, parse_nfse_xml

FIXTURE = Path(__file__).parent / "fixtures" / "nfse_nacional_exemplo.xml"


def test_parse_national_nfse() -> None:
    invoice = parse_nfse_xml(FIXTURE.read_text(encoding="utf-8"))
    assert invoice.number == "123"
    assert invoice.issue_date == date(2026, 9, 15)
    assert invoice.competence_date == date(2026, 9, 15)
    assert invoice.amount == Decimal("1000.00")
    assert invoice.iss_amount == Decimal("50.00")
    assert invoice.tax_withheld
    assert invoice.iss_withheld == Decimal("50.00")
    assert invoice.provider_document == "11222333000181"
    assert invoice.provider_name == "PRESTADOR FICTICIO LTDA"
    assert invoice.taker_document == "12166128000109"
    assert invoice.status == "100"
    assert invoice.version == "1.00"
    assert invoice.service_code == "070501"
    assert invoice.service_location == "5300108 - Brasília"
    assert (invoice.pis, invoice.cofins) == (Decimal("6.50"), Decimal("30.00"))
    assert invoice.csll == invoice.social_contributions_withheld == Decimal("46.50")
    assert invoice.inss == Decimal("110.00")
    assert invoice.irrf == Decimal("0.00")
    assert invoice.deductions == Decimal("0")
    assert invoice.net_amount == Decimal("793.50")
    assert invoice.raw_source == "xml"
    assert invoice.access_key == "53001082211222333000181000000000000126090000000001"


def test_iss_not_withheld_and_missing_values() -> None:
    xml = FIXTURE.read_text(encoding="utf-8")
    xml = xml.replace("<tpRetISSQN>2</tpRetISSQN>", "<tpRetISSQN>1</tpRetISSQN>")
    xml = xml.replace("<vISSQN>50.00</vISSQN>", "")
    invoice = parse_nfse_xml(xml, access_key="CHAVE")
    assert not invoice.tax_withheld
    assert invoice.iss_amount == invoice.iss_withheld == Decimal("0")
    assert invoice.access_key == "CHAVE"


@pytest.mark.parametrize(
    "xml", ["<x/>", "nao e xml", "<NFSe xmlns='http://www.sped.fazenda.gov.br/nfse'/>"]
)
def test_rejects_other_documents(xml: str) -> None:
    with pytest.raises(NfseParseError):
        parse_nfse_xml(xml)
