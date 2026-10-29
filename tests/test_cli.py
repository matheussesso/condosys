from pathlib import Path

import pytest
from typer.testing import CliRunner

from condosys.cli import app
from condosys.config_loader import create_example_workbook
from condosys.settings import Settings
from tests.conftest import PFX_PASSWORD, MemoryKeyring, make_certificate, write_pfx

runner = CliRunner()


def test_init_creates_structure(settings: Settings) -> None:
    (settings.base_dir / ".env.example").write_text("CONDOSYS_LOG_LEVEL=INFO\n", encoding="utf-8")
    result = runner.invoke(app, ["init"])
    assert result.exit_code == 0, result.output
    for directory in ("certs", "config", "output", "data", "logs", "debug"):
        assert (settings.base_dir / directory).is_dir()
    assert settings.example_config_file.is_file()
    assert (settings.base_dir / ".env").read_text(encoding="utf-8") == "CONDOSYS_LOG_LEVEL=INFO\n"


def test_cert_add_list_remove(
    settings: Settings, the_sun_pfx: Path, memory_keyring: MemoryKeyring
) -> None:
    result = runner.invoke(app, ["cert", "add", str(the_sun_pfx)], input=f"{PFX_PASSWORD}\n")
    assert result.exit_code == 0, result.output
    assert "THE SUN FULL CONDOMINIUM RESORT" in result.output
    assert "12.166.128/0001-09" in result.output
    assert (settings.certs_dir / "the-sun.pfx").is_file()
    assert PFX_PASSWORD not in result.output.replace("Senha do certificado:", "")

    result = runner.invoke(app, ["cert", "list"])
    assert result.exit_code == 0, result.output
    assert "the-sun.pfx" in result.output
    assert "ok" in result.output

    result = runner.invoke(app, ["cert", "remove", "the-sun.pfx"])
    assert result.exit_code == 0
    assert memory_keyring.store == {}

    result = runner.invoke(app, ["cert", "list"])
    assert "não cadastrada" in result.output


def test_cert_add_wrong_password(settings: Settings, the_sun_pfx: Path) -> None:
    result = runner.invoke(app, ["cert", "add", str(the_sun_pfx)], input="errada\n")
    assert result.exit_code == 1
    assert "senha incorreta" in result.output
    assert not (settings.certs_dir / "the-sun.pfx").exists()


def test_config_sync_and_check(settings: Settings, the_sun_pfx: Path, tmp_path: Path) -> None:
    runner.invoke(app, ["cert", "add", str(the_sun_pfx)], input=f"{PFX_PASSWORD}\n")
    # The accounting firm certificate is added, but inactive.
    key, cert = make_certificate("SEMA CONTABILIDADE LTDA:11222333000181")
    sema = write_pfx(tmp_path / "sema.pfx", key, cert)
    runner.invoke(app, ["cert", "add", str(sema)], input=f"{PFX_PASSWORD}\n")
    (settings.certs_dir / "sem-senha.pfx").write_bytes(b"")

    result = runner.invoke(app, ["config", "sync"], env={"COLUMNS": "200"})
    assert result.exit_code == 0, result.output
    assert "THE SUN FULL CONDOMINIUM RESORT" in result.output
    assert "inativo (verificar)" in result.output
    assert "sem-senha.pfx: senha não cadastrada" in result.output

    result = runner.invoke(app, ["config", "sync"])
    assert "Nada a acrescentar" in result.output

    result = runner.invoke(app, ["config", "check"], env={"COLUMNS": "200"})
    assert result.exit_code == 0, result.output
    assert "Configuração válida" in result.output


def test_config_check_detects_certificate_of_another_cnpj(
    settings: Settings, tmp_path: Path
) -> None:
    create_example_workbook(settings.config_file)
    key, cert = make_certificate("OUTRO CONDOMINIO:11222333000181")
    wrong = write_pfx(tmp_path / "the-sun.pfx", key, cert)
    runner.invoke(app, ["cert", "add", str(wrong)], input=f"{PFX_PASSWORD}\n")
    (settings.certs_dir / "led.pfx").write_bytes(b"")

    result = runner.invoke(app, ["config", "check"], env={"COLUMNS": "200"})
    assert result.exit_code == 1
    assert "o certificado é de 11.222.333/0001-81" in result.output


def test_config_check_invalid_sheet(settings: Settings) -> None:
    result = runner.invoke(app, ["config", "check"])
    assert result.exit_code == 1
    assert "Planilha inválida" in result.output


def test_commands_work_from_a_subfolder(
    settings: Settings, the_sun_pfx: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from condosys.settings import get_settings

    (settings.base_dir / ".env").write_text("", encoding="utf-8")
    settings.certs_dir.mkdir()
    monkeypatch.delenv("CONDOSYS_BASE_DIR")
    monkeypatch.chdir(settings.certs_dir)
    get_settings.cache_clear()
    target = settings.certs_dir / "the-sun.pfx"
    target.write_bytes(the_sun_pfx.read_bytes())

    result = runner.invoke(app, ["cert", "add", str(target)], input=f"{PFX_PASSWORD}\n")
    assert result.exit_code == 0, result.output
    assert not (settings.certs_dir / "certs").exists()
    assert not (settings.certs_dir / "logs").exists()
    assert "Arquivo copiado" not in result.output
