import datetime as dt
from collections.abc import Iterator
from pathlib import Path

import keyring
import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.serialization import (
    BestAvailableEncryption,
    PrivateFormat,
    pkcs12,
)
from cryptography.x509.oid import NameOID
from keyring.backend import KeyringBackend
from keyring.errors import PasswordDeleteError

from condosys.certificates import ICP_BRASIL_CNPJ_OID
from condosys.settings import Settings, get_settings

PFX_PASSWORD = "s3nha-de-teste"
THE_SUN_CNPJ = "12166128000109"
PROXY_CNPJ = "11222333000181"


class MemoryKeyring(KeyringBackend):
    """Keyring backend that keeps passwords in a dict (tests never touch the real vault)."""

    priority = 1  # type: ignore[assignment]

    def __init__(self) -> None:
        super().__init__()
        self.store: dict[tuple[str, str], str] = {}

    def get_password(self, service: str, username: str) -> str | None:
        return self.store.get((service, username))

    def set_password(self, service: str, username: str, password: str) -> None:
        self.store[(service, username)] = password

    def delete_password(self, service: str, username: str) -> None:
        try:
            del self.store[(service, username)]
        except KeyError as exc:
            raise PasswordDeleteError(username) from exc


@pytest.fixture(autouse=True)
def memory_keyring() -> Iterator[MemoryKeyring]:
    previous = keyring.get_keyring()
    backend = MemoryKeyring()
    keyring.set_keyring(backend)
    yield backend
    keyring.set_keyring(previous)


def _der_octet_string(text: str) -> bytes:
    data = text.encode("ascii")
    return bytes([0x04, len(data)]) + data


def make_certificate(
    common_name: str,
    *,
    san_cnpj: str | None = None,
    issuer_name: str = "AC TESTE RFB v5",
    not_before: dt.datetime | None = None,
    not_after: dt.datetime | None = None,
) -> tuple[rsa.RSAPrivateKey, x509.Certificate]:
    """Builds a self-signed certificate shaped like an ICP-Brasil e-CNPJ."""
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    now = dt.datetime.now(dt.UTC)
    builder = (
        x509.CertificateBuilder()
        .subject_name(
            x509.Name(
                [
                    x509.NameAttribute(NameOID.COUNTRY_NAME, "BR"),
                    x509.NameAttribute(NameOID.ORGANIZATION_NAME, "ICP-Brasil"),
                    x509.NameAttribute(NameOID.COMMON_NAME, common_name),
                ]
            )
        )
        .issuer_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, issuer_name)]))
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(not_before or now - dt.timedelta(days=1))
        .not_valid_after(not_after or now + dt.timedelta(days=365))
    )
    if san_cnpj is not None:
        builder = builder.add_extension(
            x509.SubjectAlternativeName(
                [x509.OtherName(ICP_BRASIL_CNPJ_OID, _der_octet_string(san_cnpj))]
            ),
            critical=False,
        )
    return key, builder.sign(key, hashes.SHA256())


def write_pfx(
    path: Path,
    key: rsa.RSAPrivateKey,
    cert: x509.Certificate,
    password: str = PFX_PASSWORD,
    *,
    legacy: bool = False,
) -> Path:
    if legacy:
        # 3DES/SHA1, like many A1 certificates exported by Brazilian CAs.
        encryption = (
            PrivateFormat.PKCS12.encryption_builder()
            .kdf_rounds(2048)
            .key_cert_algorithm(pkcs12.PBES.PBESv1SHA1And3KeyTripleDESCBC)
            .hmac_hash(hashes.SHA1())
            .build(password.encode())
        )
    else:
        encryption = BestAvailableEncryption(password.encode())
    path.write_bytes(pkcs12.serialize_key_and_certificates(b"test", key, cert, None, encryption))
    return path


@pytest.fixture
def the_sun_pfx(tmp_path: Path) -> Path:
    key, cert = make_certificate(
        f"THE SUN FULL CONDOMINIUM RESORT:{THE_SUN_CNPJ}", san_cnpj=THE_SUN_CNPJ
    )
    return write_pfx(tmp_path / "the-sun.pfx", key, cert)


@pytest.fixture
def project_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """An empty project folder used as base dir and cwd, with fresh settings."""
    base = tmp_path / "project"
    base.mkdir()
    monkeypatch.chdir(base)
    monkeypatch.setenv("CONDOSYS_BASE_DIR", str(base))
    get_settings.cache_clear()
    yield base
    get_settings.cache_clear()


@pytest.fixture
def settings(project_dir: Path) -> Settings:
    return get_settings()
