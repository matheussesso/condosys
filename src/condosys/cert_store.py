"""Installs a certificate in the store used by Chrome/Edge, for the assisted login.

* Windows: "Current User → Personal" store, through PowerShell ``Import-PfxCertificate``
  (private key marked non-exportable).
* Linux: Chrome/Chromium NSS database ``~/.pki/nssdb``, through ``pk12util``
  (package ``libnss3-tools``).

The certificate is re-encoded (DER, AES) to a temporary file protected by a random
single-use password; the real password never appears on a command line, and the temporary
files are deleted right after the import.
"""

import logging
import os
import secrets
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from condosys.certificates import CertificateError, load_pfx, reencode_pfx

logger = logging.getLogger(__name__)

# PowerShell reads the one-time password from stdin so it is not visible in the process list.
_POWERSHELL_IMPORT = (
    "$ErrorActionPreference = 'Stop'; "
    "$password = ConvertTo-SecureString -String ([Console]::In.ReadLine()) -AsPlainText -Force; "
    "$cert = Import-PfxCertificate -FilePath $env:CONDOSYS_PFX "
    "-CertStoreLocation Cert:\\CurrentUser\\My -Password $password; "
    "$cert.Subject"
)


class CertStoreError(RuntimeError):
    """Raised when the certificate cannot be installed in the browser store."""


def nss_database_dir() -> Path:
    """Chrome/Chromium NSS database on Linux."""
    return Path.home() / ".pki" / "nssdb"


def install_certificate(pfx_path: Path, password: str) -> str:
    """Installs the certificate for the current user's Chrome/Edge.

    Args:
        pfx_path: The ``.pfx`` file.
        password: Its password.

    Returns:
        A short description of where it was installed.

    Raises:
        CertStoreError: If the platform tool is missing or the import fails.
    """
    try:
        loaded = load_pfx(pfx_path, password)
    except CertificateError as exc:
        raise CertStoreError(str(exc)) from exc
    one_time = secrets.token_urlsafe(24)
    blob = reencode_pfx(loaded, one_time)

    with tempfile.TemporaryDirectory(prefix="condosys-") as tmp:
        tmp_dir = Path(tmp)
        temp_pfx = tmp_dir / "cert.pfx"
        temp_pfx.write_bytes(blob)
        temp_pfx.chmod(0o600)
        if sys.platform == "win32":
            return _install_windows(temp_pfx, one_time)
        return _install_nss(temp_pfx, one_time, tmp_dir)


def _install_windows(temp_pfx: Path, one_time: str) -> str:
    result = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", _POWERSHELL_IMPORT],
        input=one_time + "\n",
        env={**os.environ, "CONDOSYS_PFX": str(temp_pfx)},
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise CertStoreError(f"Import-PfxCertificate falhou: {result.stderr.strip()[:500]}")
    return "Windows: Certificados do Usuário Atual → Pessoal (usado pelo Edge e pelo Chrome)"


def _install_nss(temp_pfx: Path, one_time: str, tmp_dir: Path) -> str:
    pk12util = shutil.which("pk12util")
    if pk12util is None:
        raise CertStoreError("pk12util não encontrado. Instale com: sudo apt install libnss3-tools")
    database = nss_database_dir()
    if not (database / "cert9.db").is_file():
        certutil = shutil.which("certutil")
        if certutil is None:
            raise CertStoreError(
                f"banco NSS {database} não existe. Abra o Chrome uma vez ou instale "
                "libnss3-tools e tente de novo."
            )
        database.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            [certutil, "-N", "--empty-password", "-d", f"sql:{database}"],
            check=True,
            capture_output=True,
        )
    password_file = tmp_dir / "pfx-password"
    password_file.write_text(one_time, encoding="utf-8")
    password_file.chmod(0o600)
    result = subprocess.run(
        [pk12util, "-i", str(temp_pfx), "-d", f"sql:{database}", "-w", str(password_file)],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        message = (result.stderr or result.stdout).strip()[:500]
        raise CertStoreError(f"pk12util falhou: {message}")
    return f"Linux: banco NSS do Chrome/Chromium ({database})"
