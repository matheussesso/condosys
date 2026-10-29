"""Certificate management shared by the CLI and the desktop app."""

import shutil
from dataclasses import dataclass
from pathlib import Path

from condosys.certificates import (
    CertificateError,
    list_certificate_files,
    load_pfx,
    read_certificate_info,
)
from condosys.credentials import delete_password, get_password, save_password
from condosys.models import CertificateInfo
from condosys.settings import Settings

EXPIRY_WARNING_DAYS = 30


class CertificateServiceError(RuntimeError):
    """Raised with a message meant for the user."""


@dataclass(frozen=True)
class CertificateStatus:
    """A file in ``certs/`` and what is known about it."""

    file_name: str
    has_password: bool
    info: CertificateInfo | None
    error: str | None = None

    @property
    def state(self) -> str:
        """``ok``, ``vence`` (< 30 days), ``vencido``, ``sem-senha`` or ``erro``."""
        if self.error:
            return "erro"
        if not self.has_password or self.info is None:
            return "sem-senha"
        days = self.info.days_to_expire()
        if days < 0:
            return "vencido"
        if days < EXPIRY_WARNING_DAYS:
            return "vence"
        return "ok"


def certificate_status(settings: Settings, file_name: str) -> CertificateStatus:
    """Reads one certificate of ``certs/`` with its stored password."""
    password = get_password(file_name)
    if password is None:
        return CertificateStatus(file_name, False, None)
    try:
        info = read_certificate_info(settings.certs_dir / file_name, password)
    except CertificateError as exc:
        return CertificateStatus(file_name, True, None, str(exc))
    return CertificateStatus(file_name, True, info)


def list_certificates(settings: Settings) -> list[CertificateStatus]:
    """Every ``.pfx``/``.p12`` in ``certs/``.

    Raises:
        CredentialStoreError: If the system keyring is unavailable.
    """
    return [
        certificate_status(settings, p.name) for p in list_certificate_files(settings.certs_dir)
    ]


def add_certificate(
    settings: Settings,
    source: Path,
    password: str,
    *,
    name: str | None = None,
    overwrite: bool = False,
) -> CertificateInfo:
    """Validates a ``.pfx``, copies it to ``certs/`` (if needed) and stores its password.

    Raises:
        CertificateServiceError: Wrong password, invalid file or name already taken.
        CredentialStoreError: If the system keyring is unavailable.
    """
    try:
        info = load_pfx(source, password).info
    except CertificateError as exc:
        raise CertificateServiceError(str(exc)) from exc

    target_name = name or source.name
    if not target_name.lower().endswith((".pfx", ".p12")):
        target_name += ".pfx"
    if Path(target_name).name != target_name:
        raise CertificateServiceError(f"nome inválido: {target_name}")
    target = settings.certs_dir / target_name
    settings.certs_dir.mkdir(parents=True, exist_ok=True)
    if source.resolve() != target.resolve():
        if target.exists() and not overwrite:
            raise CertificateServiceError(f"{target.name} já existe em certs/.")
        shutil.copy2(source, target)

    save_password(target.name, password)
    return info.model_copy(update={"file_name": target.name})


def forget_password(file_name: str) -> bool:
    """Removes the stored password (the file stays). Returns whether there was one."""
    return delete_password(file_name)
