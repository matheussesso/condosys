import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from condosys.adn import AdnStore, StoredDocument
from condosys.api import TOKEN_HEADER, create_app
from condosys.settings import Settings
from tests.conftest import PFX_PASSWORD, THE_SUN_CNPJ
from tests.test_adn_sync import FIXTURE

TOKEN = "t0ken"


@pytest.fixture
def client(settings: Settings) -> TestClient:
    return TestClient(create_app(settings, TOKEN), headers={TOKEN_HEADER: TOKEN})


def test_requires_token(settings: Settings) -> None:
    anonymous = TestClient(create_app(settings, TOKEN))
    assert anonymous.get("/api/health").status_code == 401
    wrong = TestClient(create_app(settings, TOKEN), headers={TOKEN_HEADER: "x"})
    assert wrong.get("/api/certificates").status_code == 401


def test_certificates_condominiums_and_collect(
    client: TestClient, settings: Settings, the_sun_pfx: Path
) -> None:
    assert client.get("/api/certificates").json() == []

    bad = client.post("/api/certificates", json={"path": str(the_sun_pfx), "password": "x"})
    assert bad.status_code == 400 and "senha incorreta" in bad.json()["detail"]

    added = client.post(
        "/api/certificates", json={"path": str(the_sun_pfx), "password": PFX_PASSWORD}
    )
    assert added.status_code == 200, added.text
    assert added.json()["state"] == "ok"
    assert added.json()["cnpj"] == "12.166.128/0001-09"
    assert PFX_PASSWORD not in added.text

    sync = client.post("/api/condominiums/sync").json()
    assert sync["added"] == ["THE SUN FULL CONDOMINIUM RESORT"]
    (row,) = client.get("/api/condominiums").json()
    assert row["active"] and row["certificate_state"] == "ok"

    patched = client.patch(f"/api/condominiums/{THE_SUN_CNPJ}", json={"notes": "teste"})
    assert patched.json()["notes"] == "teste"

    AdnStore(settings.data_dir / "adn" / THE_SUN_CNPJ).save(
        StoredDocument(1, "NFSE", "K1", FIXTURE)
    )
    job = client.post("/api/jobs/collect", json={"competence": "09/2026", "sync": False}).json()
    for _ in range(100):
        state = client.get(f"/api/jobs/{job['id']}").json()
        if state["status"] != "running":
            break
        time.sleep(0.05)
    assert state["status"] == "done", state
    assert state["results"][0]["invoices"] == 1
    assert Path(state["output_file"]).is_file()
    assert client.get("/api/outputs").json()[0]["path"] == state["output_file"]

    assert client.post("/api/jobs/collect", json={"competence": "13/2026"}).status_code == 400
