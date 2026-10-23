import datetime as dt
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.serialization import pkcs12

from condosys import credentials
from condosys.certificates import (
    CertificateError,
    list_certificate_files,
    load_pfx,
    read_certificate_info,
    reencode_pfx,
)
from tests.conftest import (
    PFX_PASSWORD,
    PROXY_CNPJ,
    THE_SUN_CNPJ,
    MemoryKeyring,
    make_certificate,
    write_pfx,
)


def test_reads_icp_brasil_certificate(the_sun_pfx: Path) -> None:
    info = read_certificate_info(the_sun_pfx, PFX_PASSWORD)
    assert info.file_name == "the-sun.pfx"
    assert info.holder_name == "THE SUN FULL CONDOMINIUM RESORT"
    assert info.cnpj == THE_SUN_CNPJ
    assert info.issuer == "AC TESTE RFB v5"
    assert 364 <= info.days_to_expire() <= 366
    assert not info.is_expired()


def test_cnpj_falls_back_to_common_name(tmp_path: Path) -> None:
    key, cert = make_certificate(f"I9 BRASIL CONTABILIDADE LTDA:{PROXY_CNPJ}")
    info = read_certificate_info(write_pfx(tmp_path / "i9.pfx", key, cert), PFX_PASSWORD)
    assert info.holder_name == "I9 BRASIL CONTABILIDADE LTDA"
    assert info.cnpj == PROXY_CNPJ


def test_certificate_without_cnpj(tmp_path: Path) -> None:
    key, cert = make_certificate("FULANO DE TAL")
    info = read_certificate_info(write_pfx(tmp_path / "pf.pfx", key, cert), PFX_PASSWORD)
    assert info.holder_name == "FULANO DE TAL"
    assert info.cnpj is None


def test_expired_certificate(tmp_path: Path) -> None:
    now = dt.datetime.now(dt.UTC)
    key, cert = make_certificate(
        "VENCIDO:12166128000109",
        not_before=now - dt.timedelta(days=400),
        not_after=now - dt.timedelta(days=10),
    )
    info = read_certificate_info(write_pfx(tmp_path / "old.pfx", key, cert), PFX_PASSWORD)
    assert info.is_expired()
    assert info.days_to_expire() < 0


def test_wrong_password(the_sun_pfx: Path) -> None:
    with pytest.raises(CertificateError, match="senha incorreta"):
        read_certificate_info(the_sun_pfx, "errada")


def test_missing_file(tmp_path: Path) -> None:
    with pytest.raises(CertificateError, match="não foi possível ler"):
        read_certificate_info(tmp_path / "nope.pfx", PFX_PASSWORD)


def test_legacy_pfx_is_reencoded(tmp_path: Path) -> None:
    key, cert = make_certificate(f"LEGADO:{THE_SUN_CNPJ}", san_cnpj=THE_SUN_CNPJ)
    loaded = load_pfx(write_pfx(tmp_path / "legacy.pfx", key, cert, legacy=True), PFX_PASSWORD)
    blob = reencode_pfx(loaded, "outra-senha")
    new_key, new_cert, _ = pkcs12.load_key_and_certificates(blob, b"outra-senha")
    assert new_cert == cert
    assert new_key is not None


def test_list_certificate_files(tmp_path: Path) -> None:
    for name in ("b.PFX", "a.p12", "notes.txt"):
        (tmp_path / name).write_bytes(b"")
    (tmp_path / "dir.pfx").mkdir()
    assert [p.name for p in list_certificate_files(tmp_path)] == ["a.p12", "b.PFX"]
    assert list_certificate_files(tmp_path / "missing") == []


def test_credentials_roundtrip(memory_keyring: MemoryKeyring) -> None:
    assert credentials.get_password("the-sun.pfx") is None
    credentials.save_password("the-sun.pfx", "segredo")
    assert credentials.get_password("THE-SUN.pfx") == "segredo"
    assert credentials.has_password("the-sun.pfx")
    assert memory_keyring.store == {("condosys", "pfx:the-sun.pfx"): "segredo"}
    assert credentials.delete_password("the-sun.pfx")
    assert not credentials.delete_password("the-sun.pfx")
    assert not credentials.has_password("the-sun.pfx")
