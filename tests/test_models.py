from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from pydantic import ValidationError

from condosys.documents import format_cnpj, is_valid_cnpj, normalize_cnpj, validate_cnpj
from condosys.exporters.excel import build_output_path
from condosys.models import AccessMode, Competence, Condominium, Invoice, parse_money


class TestCnpj:
    @pytest.mark.parametrize(
        "value",
        ["12166128000109", "12.166.128/0001-09", " 12.166.128/0001-09 ", "11222333000181"],
    )
    def test_valid_numeric(self, value: str) -> None:
        assert is_valid_cnpj(value)

    def test_valid_alphanumeric(self) -> None:
        # Official example from Receita Federal (IN RFB 2.229/2024).
        assert is_valid_cnpj("12.ABC.345/01DE-35")
        assert normalize_cnpj("12.abc.345/01de-35") == "12ABC34501DE35"

    @pytest.mark.parametrize(
        "value", ["12166128000108", "00000000000000", "1216612800010", "abc", "", "12ABC34501DE3X"]
    )
    def test_invalid(self, value: str) -> None:
        assert not is_valid_cnpj(value)

    def test_numeric_without_leading_zeros_is_padded(self) -> None:
        # 07.526.557/0001-00 typed as a number in Excel loses the leading zero.
        assert normalize_cnpj(7526557000100) == "07526557000100"
        assert is_valid_cnpj(7526557000100)

    def test_validate_raises(self) -> None:
        with pytest.raises(ValueError, match="CNPJ inválido"):
            validate_cnpj("12166128000108")

    def test_format(self) -> None:
        assert format_cnpj("12166128000109") == "12.166.128/0001-09"
        assert format_cnpj("12ABC34501DE35") == "12.ABC.345/01DE-35"
        assert format_cnpj("123") == "123"


class TestMoney:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("R$ 1.234,56", Decimal("1234.56")),
            ("1.000,00", Decimal("1000.00")),
            ("46,50", Decimal("46.50")),
            ("0,00", Decimal("0.00")),
            ("1234.56", Decimal("1234.56")),
            ("", Decimal("0")),
            (Decimal("10.5"), Decimal("10.5")),
        ],
    )
    def test_parse(self, raw: object, expected: Decimal) -> None:
        assert parse_money(raw) == expected

    def test_float_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="float"):
            parse_money(10.5)

    def test_invalid_string(self) -> None:
        with pytest.raises(ValueError, match="inválido"):
            parse_money("abc")


class TestCompetence:
    def test_parse_and_bounds(self) -> None:
        competence = Competence.parse("09/2026")
        assert competence.first_day == date(2026, 9, 1)
        assert competence.last_day == date(2026, 9, 30)
        assert competence.label == "09/2026"
        assert competence.slug == "2026-09"

    def test_leap_february(self) -> None:
        assert Competence.parse("2/2028").last_day == date(2028, 2, 29)

    @pytest.mark.parametrize("text", ["13/2026", "2026-09", "09/26", "setembro"])
    def test_invalid(self, text: str) -> None:
        with pytest.raises(ValueError):
            Competence.parse(text)


class TestCondominium:
    def _data(self, **overrides: object) -> dict[str, object]:
        data: dict[str, object] = {
            "active": True,
            "name": "  THE SUN  ",
            "cnpj": "12.166.128/0001-09",
            "access_mode": "DIRETO",
            "certificate": "the-sun.pfx",
        }
        data.update(overrides)
        return data

    def test_normalizes(self) -> None:
        condominium = Condominium.model_validate(self._data())
        assert condominium.name == "THE SUN"
        assert condominium.cnpj == "12166128000109"
        assert condominium.cnpj_formatted == "12.166.128/0001-09"
        assert condominium.access_mode is AccessMode.DIRECT

    def test_invalid_cnpj(self) -> None:
        with pytest.raises(ValidationError, match="CNPJ inválido"):
            Condominium.model_validate(self._data(cnpj="12166128000100"))

    def test_invalid_access_mode(self) -> None:
        with pytest.raises(ValidationError):
            Condominium.model_validate(self._data(access_mode="OUTRO"))

    def test_certificate_must_exist_when_context_given(self, tmp_path: Path) -> None:
        with pytest.raises(ValidationError, match="não encontrado"):
            Condominium.model_validate(self._data(), context={"certs_dir": tmp_path})
        (tmp_path / "the-sun.pfx").write_bytes(b"")
        assert Condominium.model_validate(self._data(), context={"certs_dir": tmp_path})

    def test_certificate_extension(self) -> None:
        with pytest.raises(ValidationError, match=r"\.pfx"):
            Condominium.model_validate(self._data(certificate="the-sun.txt"))


def test_invoice_parses_brazilian_values() -> None:
    invoice = Invoice.model_validate(
        {
            "number": "123",
            "issue_date": date(2026, 9, 15),
            "amount": "1.000,00",
            "iss_amount": "50,00",
            "tax_withheld": True,
            "provider_document": "11.222.333/0001-81",
            "provider_name": "PRESTADOR LTDA",
            "status": "Normal",
            "version": "1",
        }
    )
    assert invoice.amount == Decimal("1000.00")
    assert invoice.provider_document == "11222333000181"


def test_output_path_is_windows_safe(tmp_path: Path) -> None:
    path = build_output_path(tmp_path, Competence.parse("09/2026"), datetime(2026, 10, 5, 14, 3, 9))
    assert path.name == "notas_2026-09_20261005-140309.xlsx"
    assert ":" not in path.name
