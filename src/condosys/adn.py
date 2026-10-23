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
import logging
import secrets
import ssl
import tempfile
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
            try:
                raw = base64.b64decode(value, validate=True)
            except (binascii.Error, ValueError):
                return
            if raw.startswith(_GZIP_MAGIC):
                found.append(gzip.decompress(raw).decode("utf-8", errors="replace"))

    walk(payload)
    return found
