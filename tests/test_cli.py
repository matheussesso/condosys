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
    for directory in ("certs", "config", "output", "logs", "debug"):
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


def test_config_check(settings: Settings, the_sun_pfx: Path, tmp_path: Path) -> None:
    create_example_workbook(settings.config_file)
    runner.invoke(app, ["cert", "add", str(the_sun_pfx)], input=f"{PFX_PASSWORD}\n")
    # The proxy certificate belongs to another company, as expected for PROCURACAO.
    key, cert = make_certificate("I9 BRASIL LTDA:11222333000181")
    i9 = write_pfx(tmp_path / "i9-brasil.pfx", key, cert)
    runner.invoke(app, ["cert", "add", str(i9)], input=f"{PFX_PASSWORD}\n")
    # sema.pfx (inactive row) exists but has no password.
    (settings.certs_dir / "sema.pfx").write_bytes(b"")

    result = runner.invoke(app, ["config", "check"], env={"COLUMNS": "200"})
    assert result.exit_code == 0, result.output
    assert "procuração via I9 BRASIL LTDA" in result.output
    assert "Configuração válida" in result.output


def test_config_check_detects_wrong_direct_certificate(settings: Settings, tmp_path: Path) -> None:
    create_example_workbook(settings.config_file)
    key, cert = make_certificate("OUTRO CONDOMINIO:11222333000181")
    wrong = write_pfx(tmp_path / "the-sun.pfx", key, cert)
    runner.invoke(app, ["cert", "add", str(wrong)], input=f"{PFX_PASSWORD}\n")
    for name in ("i9-brasil.pfx", "sema.pfx"):
        (settings.certs_dir / name).write_bytes(b"")

    result = runner.invoke(app, ["config", "check"], env={"COLUMNS": "200"})
    assert result.exit_code == 1
    assert "modo DIRETO, mas o certificado é de 11.222.333/0001-81" in result.output


def test_config_check_invalid_sheet(settings: Settings) -> None:
    result = runner.invoke(app, ["config", "check"])
    assert result.exit_code == 1
    assert "Planilha inválida" in result.output


@pytest.mark.browser
def test_login_test_without_password_explains(settings: Settings) -> None:
    create_example_workbook(settings.config_file)
    settings.certs_dir.mkdir(parents=True, exist_ok=True)
    for name in ("the-sun.pfx", "i9-brasil.pfx", "sema.pfx"):
        (settings.certs_dir / name).write_bytes(b"")
    result = runner.invoke(app, ["login-test", "the sun", "--headless"], env={"COLUMNS": "200"})
    if "não foi possível abrir o navegador" in result.output:
        pytest.skip("Chromium indisponível")
    assert result.exit_code == 1, result.output
    assert "senha do certificado the-sun.pfx não cadastrada" in result.output
