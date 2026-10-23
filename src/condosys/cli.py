"""Command line interface (Typer)."""

import logging
import shutil
from datetime import date
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

from condosys import __version__
from condosys.certificates import CertificateError, list_certificate_files, read_certificate_info
from condosys.config_loader import (
    CondominiumNotFoundError,
    ConfigError,
    create_example_workbook,
    find_condominium,
    load_condominiums,
)
from condosys.credentials import CredentialStoreError, delete_password, get_password, save_password
from condosys.documents import format_cnpj
from condosys.logging_setup import setup_logging
from condosys.models import AccessMode, CertificateInfo, Condominium
from condosys.settings import Settings, get_settings

logger = logging.getLogger("condosys.cli")
console = Console()

EXPIRY_WARNING_DAYS = 30
FALLBACK_ENV = "# Configurações do condosys (veja .env.example no repositório).\n"

app = typer.Typer(
    help="condosys — automação da rotina fiscal de condomínios (ISSNet DF).",
    no_args_is_help=True,
    rich_markup_mode="rich",
)
cert_app = typer.Typer(help="Certificados A1 (.pfx) e suas senhas.", no_args_is_help=True)
config_app = typer.Typer(help="Planilha de condomínios.", no_args_is_help=True)
app.add_typer(cert_app, name="cert")
app.add_typer(config_app, name="config")


def _version_callback(value: bool) -> None:
    if value:
        console.print(f"condosys {__version__}")
        raise typer.Exit()


@app.callback()
def main(
    verbose: Annotated[
        bool, typer.Option("--verbose", "-v", help="Mostra mensagens de depuração.")
    ] = False,
    version: Annotated[
        bool,
        typer.Option(
            "--version", callback=_version_callback, is_eager=True, help="Mostra a versão."
        ),
    ] = False,
) -> None:
    """Configura o log antes de cada comando."""
    settings = get_settings()
    setup_logging(settings.logs_dir, "DEBUG" if verbose else settings.log_level)


def _fail(message: str, code: int = 1) -> typer.Exit:
    console.print(f"[bold red]Erro:[/] {message}")
    return typer.Exit(code)


def _expiry_style(days: int) -> str:
    if days < 0:
        return "bold red"
    if days < EXPIRY_WARNING_DAYS:
        return "yellow"
    return "green"


def _print_certificate(info: CertificateInfo) -> None:
    days = info.days_to_expire()
    table = Table(show_header=False, box=None)
    table.add_row("Arquivo", info.file_name)
    table.add_row("Titular", info.holder_name)
    table.add_row("CNPJ", format_cnpj(info.cnpj) if info.cnpj else "[yellow]não encontrado[/]")
    table.add_row("Emissor", info.issuer)
    table.add_row(
        "Validade",
        f"{info.not_before:%d/%m/%Y} a {info.not_after:%d/%m/%Y} "
        f"[{_expiry_style(days)}]({days} dias)[/]",
    )
    console.print(table)


def _load_condominiums(settings: Settings, check_certs: bool = True) -> list[Condominium]:
    try:
        return load_condominiums(settings.config_file, settings.certs_dir if check_certs else None)
    except ConfigError as exc:
        console.print(f"[bold red]Planilha inválida:[/] {settings.config_file}")
        for error in exc.errors:
            console.print(f"  - {error}")
        raise typer.Exit(1) from exc


# --- init --------------------------------------------------------------------------------


@app.command()
def init() -> None:
    """Cria as pastas, a planilha de exemplo e o arquivo .env."""
    settings = get_settings()
    for directory in (
        settings.certs_dir,
        settings.config_file.parent,
        settings.output_dir,
        settings.logs_dir,
        settings.debug_dir,
    ):
        directory.mkdir(parents=True, exist_ok=True)
        console.print(f"Pasta pronta: {directory}")

    example = create_example_workbook(settings.example_config_file)
    console.print(f"Planilha de exemplo gerada: {example}")

    env_file = settings.base_dir / ".env"
    env_example = settings.base_dir / ".env.example"
    if env_file.exists():
        console.print(f".env já existe, mantido: {env_file}")
    elif env_example.is_file():
        shutil.copyfile(env_example, env_file)
        console.print(f".env criado a partir de .env.example: {env_file}")
    else:
        env_file.write_text(FALLBACK_ENV, encoding="utf-8")
        console.print(f".env criado: {env_file}")

    if not settings.config_file.exists():
        console.print(
            f"\n[bold]Próximo passo:[/] copie {example.name} para {settings.config_file.name} "
            "e preencha os condomínios."
        )


# --- cert --------------------------------------------------------------------------------


@cert_app.command("add")
def cert_add(
    pfx_file: Annotated[
        Path, typer.Argument(exists=True, dir_okay=False, help="Arquivo .pfx/.p12.")
    ],
    name: Annotated[
        str | None,
        typer.Option("--name", "-n", help="Nome do arquivo dentro de certs/ (ex.: the-sun.pfx)."),
    ] = None,
    overwrite: Annotated[
        bool, typer.Option("--overwrite", help="Substitui um arquivo de mesmo nome em certs/.")
    ] = False,
) -> None:
    """Valida o .pfx, guarda a senha no cofre do sistema e copia o arquivo para certs/."""
    settings = get_settings()
    password = typer.prompt("Senha do certificado", hide_input=True)
    try:
        info = read_certificate_info(pfx_file, password)
    except CertificateError as exc:
        raise _fail(str(exc)) from exc

    target_name = name or pfx_file.name
    if not target_name.lower().endswith((".pfx", ".p12")):
        target_name += ".pfx"
    target = settings.certs_dir / target_name
    settings.certs_dir.mkdir(parents=True, exist_ok=True)
    if pfx_file.resolve() != target.resolve():
        if target.exists() and not overwrite:
            raise _fail(f"{target} já existe. Use --overwrite ou --name.")
        shutil.copy2(pfx_file, target)
        console.print(f"Arquivo copiado para {target}")

    try:
        save_password(target.name, password)
    except CredentialStoreError as exc:
        raise _fail(str(exc)) from exc

    console.print("[green]Certificado válido. Senha salva no cofre do sistema.[/]")
    _print_certificate(info.model_copy(update={"file_name": target.name}))
    if info.is_expired():
        console.print("[bold red]Atenção: certificado vencido.[/]")


@cert_app.command("list")
def cert_list() -> None:
    """Lista os certificados em certs/ com titular, CNPJ e validade."""
    settings = get_settings()
    files = list_certificate_files(settings.certs_dir)
    if not files:
        console.print(f"Nenhum certificado em {settings.certs_dir}.")
        return

    table = Table(title=f"Certificados em {settings.certs_dir}")
    for column in ("Arquivo", "Titular", "CNPJ", "Validade", "Dias p/ vencer", "Senha"):
        table.add_column(column)
    for path in files:
        try:
            password = get_password(path.name)
        except CredentialStoreError as exc:
            raise _fail(str(exc)) from exc
        if password is None:
            table.add_row(path.name, "-", "-", "-", "-", "[yellow]não cadastrada[/]")
            continue
        try:
            info = read_certificate_info(path, password)
        except CertificateError as exc:
            table.add_row(path.name, f"[red]{exc}[/]", "-", "-", "-", "[red]inválida?[/]")
            continue
        days = info.days_to_expire()
        table.add_row(
            path.name,
            info.holder_name,
            format_cnpj(info.cnpj) if info.cnpj else "-",
            f"{info.not_after:%d/%m/%Y}",
            f"[{_expiry_style(days)}]{days}[/]",
            "[green]ok[/]",
        )
    console.print(table)


@cert_app.command("remove")
def cert_remove(
    name: Annotated[str, typer.Argument(help="Nome do arquivo em certs/ (ex.: the-sun.pfx).")],
) -> None:
    """Remove a senha do certificado do cofre do sistema (o arquivo é mantido)."""
    try:
        removed = delete_password(name)
    except CredentialStoreError as exc:
        raise _fail(str(exc)) from exc
    if removed:
        console.print(f"Senha de {name} removida do cofre do sistema.")
    else:
        console.print(f"[yellow]Nenhuma senha cadastrada para {name}.[/]")


# --- config ------------------------------------------------------------------------------


def _check_row(settings: Settings, condominium: Condominium, today: date) -> tuple[str, str]:
    """Returns (status markup, message) for one condominium."""
    try:
        password = get_password(condominium.certificate)
    except CredentialStoreError as exc:
        return "[red]ERRO[/]", str(exc)
    if password is None:
        return (
            "[red]ERRO[/]",
            f"senha não cadastrada (condosys cert add certs/{condominium.certificate})",
        )
    try:
        info = read_certificate_info(settings.certs_dir / condominium.certificate, password)
    except CertificateError as exc:
        return "[red]ERRO[/]", str(exc)

    problems: list[str] = []
    warnings: list[str] = []
    days = info.days_to_expire(today)
    if days < 0:
        problems.append(f"certificado vencido em {info.not_after:%d/%m/%Y}")
    elif days < EXPIRY_WARNING_DAYS:
        warnings.append(f"certificado vence em {days} dias")
    if condominium.access_mode is AccessMode.DIRECT:
        if info.cnpj is None:
            warnings.append("CNPJ não encontrado no certificado")
        elif info.cnpj != condominium.cnpj:
            problems.append(
                f"modo DIRETO, mas o certificado é de {format_cnpj(info.cnpj)} ({info.holder_name})"
            )
        details = info.holder_name
    else:
        details = f"procuração via {info.holder_name}"

    message = "; ".join([*problems, *warnings, details])
    if problems:
        return "[red]ERRO[/]", message
    if warnings:
        return "[yellow]ALERTA[/]", message
    return "[green]OK[/]", message


@config_app.command("check")
def config_check() -> None:
    """Valida condominios.xlsx e cruza com os certificados."""
    settings = get_settings()
    condominiums = _load_condominiums(settings)
    table = Table(title=f"{settings.config_file.name}: {len(condominiums)} condomínios")
    for column in ("Linha", "Ativo", "Nome", "CNPJ", "Acesso", "Certificado", "Status", "Detalhe"):
        table.add_column(column)

    today = date.today()
    has_error = False
    for condominium in condominiums:
        status, message = _check_row(settings, condominium, today)
        has_error = has_error or ("ERRO" in status and condominium.active)
        table.add_row(
            str(condominium.row),
            "SIM" if condominium.active else "[dim]NÃO[/]",
            condominium.name,
            condominium.cnpj_formatted,
            condominium.access_mode.value,
            condominium.certificate,
            status,
            message,
        )
    console.print(table)
    if has_error:
        raise _fail("há condomínios ativos com problemas.")
    console.print("[green]Configuração válida.[/]")


def resolve_condominium(settings: Settings, query: str) -> Condominium:
    """Finds a condominium of the spreadsheet by name or CNPJ, exiting on failure."""
    condominiums = _load_condominiums(settings)
    try:
        return find_condominium(condominiums, query)
    except CondominiumNotFoundError as exc:
        raise _fail(str(exc)) from exc
