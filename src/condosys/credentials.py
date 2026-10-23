"""Storage of ``.pfx`` passwords in the OS keyring.

Windows uses the Credential Manager; Linux uses the Secret Service (GNOME Keyring,
KWallet). Passwords are never written to files, code or logs.
"""

import logging

import keyring
from keyring.errors import KeyringError, PasswordDeleteError

logger = logging.getLogger(__name__)

SERVICE_NAME = "condosys"


class CredentialStoreError(RuntimeError):
    """Raised when the OS keyring is unavailable or fails."""


def _account(certificate_file: str) -> str:
    # Keyed by file name (e.g. "the-sun.pfx"), case-insensitive because Windows paths are.
    return f"pfx:{certificate_file.strip().lower()}"


def _unavailable(exc: Exception) -> CredentialStoreError:
    return CredentialStoreError(
        "Não foi possível acessar o cofre de senhas do sistema "
        f"({type(exc).__name__}: {exc}). No Linux, verifique se o GNOME Keyring ou o "
        "KWallet está instalado e desbloqueado; no Windows, o Gerenciador de Credenciais."
    )


def save_password(certificate_file: str, password: str) -> None:
    """Stores the password of a certificate file.

    Raises:
        CredentialStoreError: If the keyring is unavailable.
    """
    try:
        keyring.set_password(SERVICE_NAME, _account(certificate_file), password)
    except KeyringError as exc:
        raise _unavailable(exc) from exc
    logger.debug("Senha do certificado %s salva no cofre do sistema.", certificate_file)


def get_password(certificate_file: str) -> str | None:
    """Returns the stored password, or ``None`` if there is none.

    Raises:
        CredentialStoreError: If the keyring is unavailable.
    """
    try:
        return keyring.get_password(SERVICE_NAME, _account(certificate_file))
    except KeyringError as exc:
        raise _unavailable(exc) from exc


def has_password(certificate_file: str) -> bool:
    """Whether a password is stored for the certificate file."""
    return get_password(certificate_file) is not None


def delete_password(certificate_file: str) -> bool:
    """Removes the stored password.

    Returns:
        True if a password was removed, False if there was none.

    Raises:
        CredentialStoreError: If the keyring is unavailable.
    """
    try:
        keyring.delete_password(SERVICE_NAME, _account(certificate_file))
    except PasswordDeleteError:
        return False
    except KeyringError as exc:
        raise _unavailable(exc) from exc
    logger.debug("Senha do certificado %s removida do cofre do sistema.", certificate_file)
    return True
