"""Reading A1 (``.pfx``/``.p12``) certificates: holder, CNPJ, issuer and validity."""

import re
from dataclasses import dataclass
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives.asymmetric.types import PrivateKeyTypes
from cryptography.hazmat.primitives.serialization import BestAvailableEncryption, pkcs12
from cryptography.x509.oid import NameOID

from condosys.documents import is_valid_cnpj, normalize_cnpj
from condosys.models import CertificateInfo

# ICP-Brasil: OID of the company CNPJ inside the SubjectAltName (otherName).
ICP_BRASIL_CNPJ_OID = x509.ObjectIdentifier("2.16.76.1.3.3")
CERT_EXTENSIONS = (".pfx", ".p12")

# e-CNPJ subjects usually look like "COMPANY NAME:12345678000199".
_CN_WITH_DOCUMENT_RE = re.compile(r"^(?P<name>.+?):(?P<doc>[0-9A-Za-z./\-]{11,18})$")


class CertificateError(ValueError):
    """Raised when a certificate file cannot be opened."""


@dataclass(frozen=True)
class LoadedCertificate:
    """A decrypted certificate kept only in memory."""

    info: CertificateInfo
    key: PrivateKeyTypes
    certificate: x509.Certificate
    chain: list[x509.Certificate]


def load_pfx(path: Path, password: str) -> LoadedCertificate:
    """Opens a ``.pfx`` with its password.

    Args:
        path: Certificate file.
        password: Certificate password.

    Returns:
        The decrypted certificate and its public data.

    Raises:
        CertificateError: If the file is missing, the password is wrong or the file is invalid.
    """
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise CertificateError(f"não foi possível ler {path}: {exc}") from exc
    try:
        key, cert, chain = pkcs12.load_key_and_certificates(data, password.encode("utf-8"))
    except ValueError as exc:
        raise CertificateError(
            f"não foi possível abrir {path.name}: senha incorreta ou arquivo inválido"
        ) from exc
    if key is None or cert is None:
        raise CertificateError(f"{path.name} não contém chave privada e certificado")
    return LoadedCertificate(
        info=certificate_info(cert, path.name), key=key, certificate=cert, chain=list(chain)
    )


def read_certificate_info(path: Path, password: str) -> CertificateInfo:
    """Shortcut for ``load_pfx(path, password).info``."""
    return load_pfx(path, password).info


def certificate_info(cert: x509.Certificate, file_name: str) -> CertificateInfo:
    """Extracts the public data of an X.509 certificate."""
    common_name = _first_attribute(cert.subject, NameOID.COMMON_NAME)
    holder_name = common_name
    cn_document: str | None = None
    match = _CN_WITH_DOCUMENT_RE.match(common_name)
    if match:
        holder_name = match.group("name").strip()
        cn_document = normalize_cnpj(match.group("doc"))

    cnpj = _cnpj_from_san(cert)
    if cnpj is None and cn_document is not None and is_valid_cnpj(cn_document):
        cnpj = cn_document

    return CertificateInfo(
        file_name=file_name,
        holder_name=holder_name or cert.subject.rfc4514_string(),
        cnpj=cnpj,
        issuer=_first_attribute(cert.issuer, NameOID.COMMON_NAME) or cert.issuer.rfc4514_string(),
        not_before=cert.not_valid_before_utc,
        not_after=cert.not_valid_after_utc,
        serial_number=format(cert.serial_number, "X"),
    )


def reencode_pfx(loaded: LoadedCertificate, password: str) -> bytes:
    """Serializes the certificate back to PKCS#12 using modern encryption (AES-256).

    Many A1 certificates are exported with legacy RC2/3DES encryption, which the browser's
    OpenSSL 3 refuses. The result lives only in memory.

    Args:
        loaded: Certificate opened with :func:`load_pfx`.
        password: Password used to protect the new PKCS#12 blob.

    Returns:
        The PKCS#12 bytes.
    """
    return pkcs12.serialize_key_and_certificates(
        name=loaded.info.holder_name.encode("utf-8"),
        key=loaded.key,  # type: ignore[arg-type]
        cert=loaded.certificate,
        cas=loaded.chain or None,
        encryption_algorithm=BestAvailableEncryption(password.encode("utf-8")),
    )


def list_certificate_files(certs_dir: Path) -> list[Path]:
    """Lists ``.pfx``/``.p12`` files in a directory, sorted by name."""
    if not certs_dir.is_dir():
        return []
    return sorted(
        (p for p in certs_dir.iterdir() if p.is_file() and p.suffix.lower() in CERT_EXTENSIONS),
        key=lambda p: p.name.lower(),
    )


def _first_attribute(name: x509.Name, oid: x509.ObjectIdentifier) -> str:
    attributes = name.get_attributes_for_oid(oid)
    if not attributes:
        return ""
    value = attributes[0].value
    return value if isinstance(value, str) else value.decode("utf-8", errors="replace")


def _cnpj_from_san(cert: x509.Certificate) -> str | None:
    try:
        san = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
    except x509.ExtensionNotFound:
        return None
    for other in san.get_values_for_type(x509.OtherName):
        if other.type_id != ICP_BRASIL_CNPJ_OID:
            continue
        candidate = normalize_cnpj(_der_string_content(other.value))
        if is_valid_cnpj(candidate):
            return candidate
    return None


def _der_string_content(der: bytes) -> str:
    # otherName values are a single DER string (OCTET STRING, PrintableString, UTF8String...).
    if len(der) < 2:
        return ""
    length = der[1]
    offset = 2
    if length & 0x80:
        size = length & 0x7F
        length = int.from_bytes(der[2 : 2 + size], "big")
        offset = 2 + size
    return der[offset : offset + length].decode("latin-1", errors="replace")
