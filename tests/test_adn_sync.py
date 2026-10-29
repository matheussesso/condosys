import base64
import gzip
from datetime import date
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from condosys.adn import AdnError, AdnResponse, AdnStore, StoredDocument, sync_documents
from condosys.cli import app
from condosys.models import Competence
from condosys.services.adn_invoices import taken_invoices
from condosys.settings import Settings
from tests.conftest import PFX_PASSWORD, THE_SUN_CNPJ

FIXTURE = (Path(__file__).parent / "fixtures" / "nfse_nacional_exemplo.xml").read_text(
    encoding="utf-8"
)


def _packed(xml: str) -> str:
    return base64.b64encode(gzip.compress(xml.encode())).decode()


def _item(nsu: int, kind: str = "NFSE") -> dict[str, Any]:
    return {
        "NSU": nsu,
        "ChaveAcesso": f"K{nsu}",
        "TipoDocumento": kind,
        "ArquivoXml": _packed(FIXTURE),
    }


class FakeAdn:
    """Serves `total` documents in batches of 50, like the ADN."""

    def __init__(self, total: int) -> None:
        self.total = total
        self.calls: list[tuple[int, str | None]] = []

    def __call__(
        self, base_url: str, loaded: Any, nsu: int, *, cnpj: str | None = None
    ) -> AdnResponse:
        self.calls.append((nsu, cnpj))
        items = [_item(n) for n in range(nsu + 1, min(nsu + 50, self.total) + 1)]
        if not items:
            payload = {"StatusProcessamento": "NENHUM_DOCUMENTO_LOCALIZADO", "LoteDFe": []}
            return AdnResponse(404, "url", payload, "")
        payload = {"StatusProcessamento": "DOCUMENTOS_LOCALIZADOS", "LoteDFe": items}
        return AdnResponse(200, "url", payload, "")


def test_sync_pages_and_resumes(tmp_path: Path) -> None:
    store = AdnStore(tmp_path / "adn" / THE_SUN_CNPJ)
    fake = FakeAdn(total=120)
    result = sync_documents("https://adn", None, store, pause_s=0, max_batches=2, fetch=fake)  # type: ignore[arg-type]
    assert (result.new_documents, result.batches, result.last_nsu, result.finished) == (
        100,
        2,
        100,
        False,
    )
    assert [nsu for nsu, _ in fake.calls] == [0, 50]
    assert store.last_nsu == 100

    result = sync_documents("https://adn", None, store, pause_s=0, fetch=fake)  # type: ignore[arg-type]
    assert (result.new_documents, result.last_nsu, result.finished) == (20, 120, True)
    docs = list(store.documents())
    assert [d.nsu for d in docs] == list(range(1, 121))
    assert docs[0].access_key == "K1"
    assert docs[0].xml == FIXTURE

    result = sync_documents("https://adn", None, store, pause_s=0, fetch=fake)  # type: ignore[arg-type]
    assert (result.new_documents, result.finished) == (0, True)
    assert result.status == "NENHUM_DOCUMENTO_LOCALIZADO"


def test_sync_ignores_repeated_nsus(tmp_path: Path) -> None:
    store = AdnStore(tmp_path / "s")
    store.set_last_nsu(10)

    def fetch(base_url: str, loaded: Any, nsu: int, *, cnpj: str | None = None) -> AdnResponse:
        items = [_item(n) for n in (9, 10, 11)]  # overlap with what is stored
        return AdnResponse(
            200, "u", {"StatusProcessamento": "DOCUMENTOS_LOCALIZADOS", "LoteDFe": items}, ""
        )

    result = sync_documents("https://adn", None, store, pause_s=0, fetch=fetch)  # type: ignore[arg-type]
    assert result.new_documents == 1
    assert store.last_nsu == 11


def test_sync_error_answer(tmp_path: Path) -> None:
    def fetch(base_url: str, loaded: Any, nsu: int, *, cnpj: str | None = None) -> AdnResponse:
        return AdnResponse(403, "u", None, "certificado recusado")

    with pytest.raises(AdnError, match="HTTP 403: certificado recusado"):
        sync_documents("https://adn", None, AdnStore(tmp_path / "s"), fetch=fetch)  # type: ignore[arg-type]


def test_taken_invoices_filters_taker_competence_and_kind() -> None:
    other_taker = FIXTURE.replace("<CNPJ>12166128000109</CNPJ>", "<CNPJ>19516329000138</CNPJ>")
    october = FIXTURE.replace("2026-09-15T10:00:00", "2026-10-01T10:00:00")
    docs = [
        StoredDocument(1, "NFSE", "A", FIXTURE),
        StoredDocument(2, "NFSE", "B", other_taker),
        StoredDocument(3, "NFSE", "C", october),
        StoredDocument(4, "EVENTO", "D", FIXTURE),
        StoredDocument(5, "NFSE", "E", "<quebrado"),
    ]
    found = taken_invoices(docs, THE_SUN_CNPJ, Competence.parse("09/2026"))
    assert [i.access_key for i in found] == ["A"]
    assert found[0].issue_date == date(2026, 9, 15)


def test_notas_command_offline(settings: Settings, the_sun_pfx: Path) -> None:
    runner = CliRunner()
    runner.invoke(app, ["cert", "add", str(the_sun_pfx)], input=f"{PFX_PASSWORD}\n")
    runner.invoke(app, ["config", "sync"])
    store = AdnStore(settings.data_dir / "adn" / THE_SUN_CNPJ)
    store.save(StoredDocument(1, "NFSE", "A", FIXTURE))

    result = runner.invoke(
        app, ["notas", "the sun", "-c", "09/2026", "--sem-sincronizar"], env={"COLUMNS": "220"}
    )
    assert result.exit_code == 0, result.output
    assert "PRESTADOR FICTICIO" in result.output
    assert "1.000,00" in result.output and "793,50" in result.output
    assert "1 notas" in result.output
