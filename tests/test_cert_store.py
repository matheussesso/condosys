import subprocess
from pathlib import Path
from typing import Any

import pytest
from cryptography.hazmat.primitives.serialization import pkcs12

from condosys import cert_store
from condosys.cert_store import CertStoreError, install_certificate
from tests.conftest import PFX_PASSWORD


class FakeRun:
    def __init__(self, returncode: int = 0) -> None:
        self.calls: list[dict[str, Any]] = []
        self.returncode = returncode

    def __call__(self, args: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        files = {}
        for arg in args:
            if len(arg) < 255 and Path(arg).is_file():
                files[arg] = Path(arg).read_bytes()
        if "env" in kwargs and "CONDOSYS_PFX" in kwargs["env"]:
            pfx = kwargs["env"]["CONDOSYS_PFX"]
            files[pfx] = Path(pfx).read_bytes()
        self.calls.append({"args": args, "kwargs": kwargs, "files": files})
        return subprocess.CompletedProcess(args, self.returncode, stdout="ok", stderr="erro")


def test_linux_import_uses_nss_and_cleans_up(
    the_sun_pfx: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("sys.platform", "linux")
    nssdb = tmp_path / "nssdb"
    nssdb.mkdir()
    (nssdb / "cert9.db").write_bytes(b"")
    monkeypatch.setattr(cert_store, "nss_database_dir", lambda: nssdb)
    monkeypatch.setattr("shutil.which", lambda name: f"/usr/bin/{name}")
    fake = FakeRun()
    monkeypatch.setattr("subprocess.run", fake)

    where = install_certificate(the_sun_pfx, PFX_PASSWORD)

    assert str(nssdb) in where
    (call,) = fake.calls
    args = call["args"]
    assert args[0] == "/usr/bin/pk12util"
    assert f"sql:{nssdb}" in args
    assert PFX_PASSWORD not in " ".join(args)
    temp_pfx = args[args.index("-i") + 1]
    password_file = args[args.index("-w") + 1]
    one_time = call["files"][password_file].decode()
    key, cert, _ = pkcs12.load_key_and_certificates(call["files"][temp_pfx], one_time.encode())
    assert key is not None and cert is not None
    assert not Path(temp_pfx).exists()  # temporary files removed
    assert not Path(password_file).exists()


def test_linux_without_pk12util(the_sun_pfx: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("sys.platform", "linux")
    monkeypatch.setattr("shutil.which", lambda name: None)
    with pytest.raises(CertStoreError, match="libnss3-tools"):
        install_certificate(the_sun_pfx, PFX_PASSWORD)


def test_windows_import_passes_password_by_stdin(
    the_sun_pfx: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("sys.platform", "win32")
    fake = FakeRun()
    monkeypatch.setattr("subprocess.run", fake)

    where = install_certificate(the_sun_pfx, PFX_PASSWORD)

    assert "Pessoal" in where
    (call,) = fake.calls
    assert call["args"][0] == "powershell"
    assert "Import-PfxCertificate" in call["args"][-1]
    assert PFX_PASSWORD not in " ".join(call["args"])
    one_time = call["kwargs"]["input"].strip()
    blob = next(iter(call["files"].values()))
    _, cert, _ = pkcs12.load_key_and_certificates(blob, one_time.encode())
    assert cert is not None


def test_failure_is_reported(the_sun_pfx: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("sys.platform", "win32")
    monkeypatch.setattr("subprocess.run", FakeRun(returncode=1))
    with pytest.raises(CertStoreError, match="Import-PfxCertificate falhou: erro"):
        install_certificate(the_sun_pfx, PFX_PASSWORD)
