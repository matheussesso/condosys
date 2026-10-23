import base64
import gzip
import http.server
import json
import ssl
import threading
from collections.abc import Iterator
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization

from condosys.adn import decode_documents, fetch_dfe, same_cnpj_root
from condosys.certificates import load_pfx
from tests.conftest import PFX_PASSWORD, THE_SUN_CNPJ, make_ca, make_certificate, write_pfx
from tests.test_browser import _pem_files, _server_certificate

XML = "<NFSe><infNFSe><tomador>12166128000109</tomador></infNFSe></NFSe>"


def _packed(xml: str) -> str:
    return base64.b64encode(gzip.compress(xml.encode())).decode()


def test_decode_documents_finds_nested_gzip() -> None:
    payload = {
        "StatusProcessamento": "DOCUMENTOS_LOCALIZADOS",
        "LoteDFe": [{"NSU": 1, "ArquivoXml": _packed(XML)}, {"NSU": 2, "Outro": "texto qualquer"}],
    }
    assert decode_documents(payload) == [XML]
    assert decode_documents(None) == []


def test_same_cnpj_root() -> None:
    assert same_cnpj_root("12166128000109", "12166128000290")
    assert not same_cnpj_root("12166128000109", "19516329000138")


class _AdnHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        peer = self.connection.getpeercert()  # type: ignore[attr-defined]
        subject = dict(item[0] for item in peer["subject"]) if peer else {}
        body = json.dumps(
            {"path": self.path, "cn": subject.get("commonName"), "LoteDFe": [_packed(XML)]}
        ).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:
        pass


@pytest.fixture
def adn_server(tmp_path: Path) -> Iterator[tuple[str, Path, Path]]:
    ca_key, ca_cert = make_ca()
    key, cert = make_certificate(f"THE SUN:{THE_SUN_CNPJ}", ca=(ca_key, ca_cert))
    pfx = write_pfx(tmp_path / "c.pfx", key, cert, legacy=True)
    client_ca = tmp_path / "client-ca.pem"
    client_ca.write_bytes(ca_cert.public_bytes(serialization.Encoding.PEM))
    server_key, server_cert = _server_certificate()
    server_pem = _pem_files(tmp_path, server_key, server_cert, "server")
    server_ca = tmp_path / "server-ca.pem"
    server_ca.write_bytes(server_cert.public_bytes(serialization.Encoding.PEM))

    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(server_pem)
    context.load_verify_locations(client_ca)
    context.verify_mode = ssl.CERT_REQUIRED
    server = http.server.ThreadingHTTPServer(("localhost", 0), _AdnHandler)
    server.socket = context.wrap_socket(server.socket, server_side=True)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"https://localhost:{server.server_address[1]}", pfx, server_ca
    server.shutdown()
    server.server_close()


def test_fetch_dfe_uses_mtls(adn_server: tuple[str, Path, Path]) -> None:
    base_url, pfx, server_ca = adn_server
    loaded = load_pfx(pfx, PFX_PASSWORD)
    response = fetch_dfe(base_url, loaded, 0, cnpj=THE_SUN_CNPJ, ca_file=server_ca)
    assert response.status_code == 200
    assert response.payload["cn"] == f"THE SUN:{THE_SUN_CNPJ}"
    assert response.payload["path"] == f"/contribuintes/DFe/0?lote=true&cnpjConsulta={THE_SUN_CNPJ}"
    assert decode_documents(response.payload) == [XML]
