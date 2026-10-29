from pathlib import Path

import pytest
from openpyxl import Workbook

from condosys.config_loader import (
    EXAMPLE_ROWS,
    CondominiumNotFoundError,
    ConfigError,
    create_example_workbook,
    find_condominium,
    load_condominiums,
    save_condominiums,
)

HEADER = ["ativo", "nome", "cnpj", "certificado", "observacoes"]


def write_sheet(path: Path, rows: list[list[object]], header: list[str] = HEADER) -> Path:
    workbook = Workbook()
    sheet = workbook.active
    assert sheet is not None
    sheet.append(header)
    for row in rows:
        sheet.append(row)
    workbook.save(path)
    return path


@pytest.fixture
def certs_dir(tmp_path: Path) -> Path:
    directory = tmp_path / "certs"
    directory.mkdir()
    for name in ("the-sun.pfx", "led.pfx", "a.pfx", "b.pfx"):
        (directory / name).write_bytes(b"")
    return directory


def test_example_workbook_is_valid(tmp_path: Path, certs_dir: Path) -> None:
    path = create_example_workbook(tmp_path / "config" / "condominios.example.xlsx")
    condominiums = load_condominiums(path, certs_dir)
    assert len(condominiums) == len(EXAMPLE_ROWS)
    the_sun = condominiums[0]
    assert the_sun.active
    assert the_sun.cnpj == "12166128000109"
    assert the_sun.certificate == "the-sun.pfx"
    assert the_sun.row == 2
    assert not condominiums[1].active


def test_accepts_accents_numbers_and_header_variants(tmp_path: Path, certs_dir: Path) -> None:
    path = write_sheet(
        tmp_path / "c.xlsx",
        [
            ["Não", "Condomínio A", 7526557000100, "a.pfx", None],
            ["sim", "Condomínio B", "11.222.333/0001-81", "b.pfx", 42],
        ],
        header=["Ativo", "Nome", "CNPJ", "Certificado", "Observações"],
    )
    first, second = load_condominiums(path, certs_dir)
    assert not first.active
    assert first.cnpj == "07526557000100"
    assert second.active
    assert second.notes == "42"


def test_old_access_mode_column_is_ignored(tmp_path: Path, certs_dir: Path) -> None:
    path = write_sheet(
        tmp_path / "c.xlsx",
        [["SIM", "The Sun", "12166128000109", "PROCURACAO", "the-sun.pfx", ""]],
        header=["ativo", "nome", "cnpj", "modo_acesso", "certificado", "observacoes"],
    )
    (condominium,) = load_condominiums(path, certs_dir)
    assert condominium.certificate == "the-sun.pfx"


def test_reports_every_error_with_row_and_column(tmp_path: Path, certs_dir: Path) -> None:
    path = write_sheet(
        tmp_path / "c.xlsx",
        [
            ["SIM", "OK", "12166128000109", "the-sun.pfx", ""],
            ["SIM", "CNPJ ruim", "12166128000100", "a.pfx", ""],
            [None, None, None, None, None],  # blank rows are skipped
            ["TALVEZ", "Outro", "11222333000181", "faltando.pfx", ""],
        ],
    )
    with pytest.raises(ConfigError) as info:
        load_condominiums(path, certs_dir)
    messages = [str(error) for error in info.value.errors]
    assert any(m.startswith("linha 3, coluna 'cnpj'") for m in messages)
    assert any(m.startswith("linha 5, coluna 'ativo'") for m in messages)
    assert any("linha 5, coluna 'certificado'" in m and "faltando.pfx" in m for m in messages)
    assert not any("linha 2" in m for m in messages)


def test_duplicates(tmp_path: Path, certs_dir: Path) -> None:
    path = write_sheet(
        tmp_path / "c.xlsx",
        [
            ["SIM", "The Sun", "12166128000109", "the-sun.pfx", ""],
            ["SIM", "THE SUN", "12166128000109", "the-sun.pfx", ""],
        ],
    )
    with pytest.raises(ConfigError) as info:
        load_condominiums(path, certs_dir)
    messages = [str(error) for error in info.value.errors]
    assert "linha 3, coluna 'nome': nome repetido (já usado na linha 2)" in messages
    assert any(m.startswith("linha 3, coluna 'cnpj': CNPJ repetido") for m in messages)


def test_missing_columns(tmp_path: Path) -> None:
    path = write_sheet(tmp_path / "c.xlsx", [], header=["nome", "cnpj"])
    with pytest.raises(ConfigError, match="ativo, certificado"):
        load_condominiums(path)


def test_missing_file(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="não encontrado"):
        load_condominiums(tmp_path / "nope.xlsx")


def test_save_round_trip(tmp_path: Path, certs_dir: Path) -> None:
    original = load_condominiums(create_example_workbook(tmp_path / "a.xlsx"), certs_dir)
    saved = load_condominiums(save_condominiums(tmp_path / "b.xlsx", original), certs_dir)
    assert [(c.name, c.cnpj, c.active, c.notes) for c in saved] == [
        (c.name, c.cnpj, c.active, c.notes) for c in original
    ]


def test_find_condominium(tmp_path: Path, certs_dir: Path) -> None:
    condominiums = load_condominiums(create_example_workbook(tmp_path / "example.xlsx"), certs_dir)
    assert find_condominium(condominiums, "the sun").cnpj == "12166128000109"
    assert find_condominium(condominiums, "12.166.128/0001-09").name.startswith("THE SUN")
    with pytest.raises(CondominiumNotFoundError, match="vários"):
        find_condominium(condominiums, "e")
    with pytest.raises(CondominiumNotFoundError, match="nenhum"):
        find_condominium(condominiums, "inexistente")
