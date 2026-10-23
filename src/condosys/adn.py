"""Client for the national NFS-e data environment (ADN) — contributor distribution API.

Official manual: "Manual dos Contribuintes — APIs do ADN" (v1.0, 12/02/2026). The
contributor (as issuer, taker or intermediary) downloads its service documents by NSU,
authenticating with an ICP-Brasil certificate over mTLS. The certificate CNPJ must have the
same CNPJ root (first 8 characters) as the queried CNPJ, so proxy certificates (Sema, i9)
cannot query the condominiums: this path is for DIRECT access only (ADR-009).

The DF shares the ISSNet documents with the ADN (DF notice of 04/11/2025).

Query parameters (``lote``, ``cnpjConsulta``) follow the public client implementations;
the response is saved raw so the exact layout can be confirmed (phase 3).
"""

import base64
import binascii
import gzip
import json
import logging
import secrets
import ssl
import tempfile
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
from cryptography.hazmat.primitives.serialization import (
    BestAvailableEncryption,
    Encoding,
    PrivateFormat,
)

from condosys.certificates import LoadedCertificate

logger = logging.getLogger(__name__)

_GZIP_MAGIC = b"\x1f\x8b"


class AdnError(RuntimeError):
    """Raised when the ADN request cannot be made."""


@dataclass(frozen=True)
class AdnResponse:
    """Raw ADN answer."""

    status_code: int
    url: str
    payload: Any
    text: str


def same_cnpj_root(first: str, second: str) -> bool:
    """Whether two normalized CNPJs share the root (first 8 characters)."""
    return first[:8] == second[:8]


def build_ssl_context(loaded: LoadedCertificate, ca_file: Path | None = None) -> ssl.SSLContext:
    """Builds an mTLS context with the certificate kept only briefly on disk.

    Python's ``ssl`` only loads client certificates from files: the certificate chain and
    the private key (encrypted with a random single-use password) go to a private
    temporary folder that is deleted as soon as they are loaded.
    """
    context = ssl.create_default_context()
    if ca_file is not None:
        context.load_verify_locations(ca_file)
    one_time = secrets.token_urlsafe(24)
    with tempfile.TemporaryDirectory(prefix="condosys-") as tmp:
        cert_file = Path(tmp) / "cert.pem"
        key_file = Path(tmp) / "key.pem"
        chain = [loaded.certificate, *loaded.chain]
        cert_file.write_bytes(b"".join(cert.public_bytes(Encoding.PEM) for cert in chain))
        key_file.write_bytes(
            loaded.key.private_bytes(
                Encoding.PEM,
                PrivateFormat.PKCS8,
                BestAvailableEncryption(one_time.encode("utf-8")),
            )
        )
        cert_file.chmod(0o600)
        key_file.chmod(0o600)
        context.load_cert_chain(cert_file, key_file, password=one_time)
    return context


def fetch_dfe(
    base_url: str,
    loaded: LoadedCertificate,
    nsu: int,
    *,
    cnpj: str | None = None,
    timeout_s: float = 60,
    ca_file: Path | None = None,
) -> AdnResponse:
    """Calls ``GET /contribuintes/DFe/{NSU}?lote=true`` once.

    Args:
        base_url: ``https://adn.nfse.gov.br`` (production).
        loaded: Certificate used for mTLS.
        nsu: Starting NSU (0 = from the beginning).
        cnpj: ``cnpjConsulta``, when different from the certificate CNPJ (same root).
        timeout_s: Request timeout.
        ca_file: Extra trusted CA for the server certificate (tests only).

    Raises:
        AdnError: On connection/TLS errors.
    """
    params: dict[str, str] = {"lote": "true"}
    if cnpj is not None:
        params["cnpjConsulta"] = cnpj
    url = f"{base_url.rstrip('/')}/contribuintes/DFe/{nsu}"
    try:
        with httpx.Client(verify=build_ssl_context(loaded, ca_file), timeout=timeout_s) as client:
            response = client.get(url, params=params, headers={"Accept": "application/json"})
    except httpx.HTTPError as exc:
        raise AdnError(f"falha ao chamar o ADN ({type(exc).__name__}: {exc})") from exc
    try:
        payload: Any = response.json()
    except ValueError:
        payload = None
    logger.info("ADN %s → HTTP %s", url, response.status_code)
    return AdnResponse(response.status_code, str(response.url), payload, response.text)


def decode_document(value: str) -> str | None:
    """Decodes one ``ArquivoXml`` (base64 + gzip); None if it is not in that format."""
    try:
        raw = base64.b64decode(value, validate=True)
    except (binascii.Error, ValueError):
        return None
    if not raw.startswith(_GZIP_MAGIC):
        return None
    return gzip.decompress(raw).decode("utf-8", errors="replace")


def decode_documents(payload: Any) -> list[str]:
    """Finds every base64+gzip document in the JSON and returns the XML texts.

    The field names are not assumed: any string that decodes to gzip is a document.
    """
    found: list[str] = []

    def walk(value: Any) -> None:
        if isinstance(value, dict):
            for item in value.values():
                walk(item)
        elif isinstance(value, list):
            for item in value:
                walk(item)
        elif isinstance(value, str) and len(value) > 20:
            xml = decode_document(value)
            if xml is not None:
                found.append(xml)

    walk(payload)
    return found


# --- local store and synchronization ---------------------------------------------------

BATCH_SIZE = 50  # documents per ADN batch (observed)
FOUND_STATUS = "DOCUMENTOS_LOCALIZADOS"


@dataclass(frozen=True)
class StoredDocument:
    """A document kept in the local store."""

    nsu: int
    kind: str
    access_key: str | None
    xml: str


class AdnStore:
    """Downloaded ADN documents of one CNPJ: ``<root>/<NSU>_<TIPO>.xml`` + ``state.json``.

    The folder holds real fiscal data and must stay out of git (``data/``).
    """

    def __init__(self, root: Path) -> None:
        self.root = root
        self._state_file = root / "state.json"

    def _state(self) -> dict[str, Any]:
        if not self._state_file.is_file():
            return {}
        data: dict[str, Any] = json.loads(self._state_file.read_text(encoding="utf-8"))
        return data

    @property
    def last_nsu(self) -> int:
        """Highest NSU already downloaded (0 = nothing yet)."""
        return int(self._state().get("last_nsu", 0))

    def set_last_nsu(self, nsu: int) -> None:
        """Records the highest NSU downloaded."""
        self.root.mkdir(parents=True, exist_ok=True)
        state = self._state()
        state["last_nsu"] = nsu
        self._state_file.write_text(json.dumps(state, indent=2), encoding="utf-8")

    def save(self, document: StoredDocument) -> Path:
        """Writes one document (overwrites the same NSU)."""
        self.root.mkdir(parents=True, exist_ok=True)
        path = self.root / f"{document.nsu:012d}_{document.kind}.xml"
        if document.access_key:
            # Sidecar file, so the XML stays exactly as received.
            path.with_suffix(".key").write_text(document.access_key, encoding="utf-8")
        path.write_text(document.xml, encoding="utf-8")
        return path

    def documents(self) -> Iterator[StoredDocument]:
        """All stored documents, by NSU."""
        if not self.root.is_dir():
            return
        for path in sorted(self.root.glob("*.xml")):
            nsu_text, _, kind = path.stem.partition("_")
            key_file = path.with_suffix(".key")
            yield StoredDocument(
                nsu=int(nsu_text),
                kind=kind,
                access_key=key_file.read_text(encoding="utf-8") if key_file.is_file() else None,
                xml=path.read_text(encoding="utf-8"),
            )


@dataclass(frozen=True)
class SyncResult:
    """Outcome of one synchronization."""

    new_documents: int
    batches: int
    last_nsu: int
    finished: bool
    status: str


Fetcher = Callable[..., AdnResponse]


def sync_documents(
    base_url: str,
    loaded: LoadedCertificate,
    store: AdnStore,
    *,
    cnpj: str | None = None,
    pause_s: float = 1.0,
    max_batches: int = 100,
    fetch: Fetcher = fetch_dfe,
) -> SyncResult:
    """Downloads the new documents of a CNPJ, batch by batch, from the last stored NSU.

    One request at a time with a pause between them. Stops at the end of the documents,
    at ``max_batches`` (the next run continues from there) or on an error answer.

    Raises:
        AdnError: On connection errors or unexpected HTTP answers.
    """
    nsu = store.last_nsu
    new = batches = 0
    status = ""
    while batches < max_batches:
        if batches:
            time.sleep(pause_s)
        response = fetch(base_url, loaded, nsu, cnpj=cnpj)
        batches += 1
        payload = response.payload if isinstance(response.payload, dict) else {}
        status = str(payload.get("StatusProcessamento", ""))
        if response.status_code == 404 or (response.status_code == 200 and status != FOUND_STATUS):
            return SyncResult(new, batches, nsu, True, status or f"HTTP {response.status_code}")
        if response.status_code != 200:
            raise AdnError(f"ADN respondeu HTTP {response.status_code}: {response.text[:300]}")
        items = payload.get("LoteDFe") or []
        highest = nsu
        for item in items:
            item_nsu = int(item.get("NSU", 0))
            xml = decode_document(str(item.get("ArquivoXml", "")))
            if xml is None or item_nsu <= nsu:
                continue
            store.save(
                StoredDocument(
                    nsu=item_nsu,
                    kind=str(item.get("TipoDocumento") or "DESCONHECIDO"),
                    access_key=item.get("ChaveAcesso"),
                    xml=xml,
                )
            )
            new += 1
            highest = max(highest, item_nsu)
        if highest <= nsu:
            return SyncResult(new, batches, nsu, True, status)
        nsu = highest
        store.set_last_nsu(nsu)
        if len(items) < BATCH_SIZE:
            return SyncResult(new, batches, nsu, True, status)
    return SyncResult(new, batches, nsu, False, status)
