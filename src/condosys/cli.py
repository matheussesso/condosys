"""Command line interface (Typer)."""

import logging
import shutil
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

from condosys import __version__
from condosys.adn import AdnError, decode_documents, fetch_dfe, same_cnpj_root
from condosys.certificates import CertificateError, LoadedCertificate, load_pfx
from condosys.config_loader import (
    CondominiumNotFoundError,
    ConfigError,
    create_example_workbook,
    find_condominium,
    load_condominiums,
)
from condosys.credentials import CredentialStoreError, get_password
from condosys.documents import format_cnpj
from condosys.exporters.excel import build_output_path, export_results
from condosys.logging_setup import setup_logging
from condosys.models import CertificateInfo, Competence, Condominium, RunResult
from condosys.services.certificates import (
    EXPIRY_WARNING_DAYS,
    CertificateServiceError,
    add_certificate,
    certificate_status,
    forget_password,
    list_certificates,
)
from condosys.services.collect import collect_all, collect_condominium
from condosys.services.condominiums import active_condominiums, sync_from_certificates
from condosys.settings import Settings, get_settings

logger = logging.getLogger("condosys.cli")
console = Console()

FALLBACK_ENV = "# Configurações do condosys (veja .env.example no repositório).\n"

app = typer.Typer(
    help="condosys — rotina fiscal de condomínios (notas tomadas via ADN, retenções).",
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


def _brl(value: Decimal) -> str:
    text = f"{value:,.2f}"
    return text.replace(",", "_").replace(".", ",").replace("_", ".")


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


def resolve_condominium(settings: Settings, query: str) -> Condominium:
    """Finds a condominium of the spreadsheet by name or CNPJ, exiting on failure."""
    condominiums = _load_condominiums(settings)
    try:
        return find_condominium(condominiums, query)
    except CondominiumNotFoundError as exc:
        raise _fail(str(exc)) from exc


def _parse_competence(text: str) -> Competence:
    try:
        return Competence.parse(text)
    except ValueError as exc:
        raise _fail(str(exc)) from exc


# --- init --------------------------------------------------------------------------------


@app.command()
def init() -> None:
    """Cria as pastas, a planilha de exemplo e o arquivo .env."""
    settings = get_settings()
    for directory in (
        settings.certs_dir,
        settings.config_file.parent,
        settings.output_dir,
        settings.data_dir,
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
            "\n[bold]Próximo passo:[/] cadastre as senhas dos certificados "
            "(condosys cert add certs/<arquivo>.pfx) e rode condosys config sync."
        )


# --- cert --------------------------------------------------------------------------------


@cert_app.command("add")
def cert_add(
    pfx_file: Annotated[
        Path, typer.Argument(exists=True, dir_okay=False, help="Arquivo .pfx/.p12.")
    ],
    name: Annotated[
        str | None,
        typer.Option("--name", "-n", help="Nome do arquivo dentro de certs/ (ex.: madison.pfx)."),
    ] = None,
    overwrite: Annotated[
        bool, typer.Option("--overwrite", help="Substitui um arquivo de mesmo nome em certs/.")
    ] = False,
) -> None:
    """Valida o .pfx, guarda a senha no cofre do sistema e copia o arquivo para certs/."""
    settings = get_settings()
    password = typer.prompt("Senha do certificado", hide_input=True)
    try:
        info = add_certificate(settings, pfx_file, password, name=name, overwrite=overwrite)
    except (CertificateServiceError, CredentialStoreError) as exc:
        raise _fail(str(exc)) from exc
    console.print("[green]Certificado válido. Senha salva no cofre do sistema.[/]")
    _print_certificate(info)
    if info.is_expired():
        console.print("[bold red]Atenção: certificado vencido.[/]")


@cert_app.command("list")
def cert_list() -> None:
    """Lista os certificados em certs/ com titular, CNPJ e validade."""
    settings = get_settings()
    try:
        statuses = list_certificates(settings)
    except CredentialStoreError as exc:
        raise _fail(str(exc)) from exc
    if not statuses:
        console.print(f"Nenhum certificado em {settings.certs_dir}.")
        return
    table = Table(title=f"Certificados em {settings.certs_dir}")
    for column in ("Arquivo", "Titular", "CNPJ", "Validade", "Dias p/ vencer", "Senha"):
        table.add_column(column)
    for status in statuses:
        if status.error:
            table.add_row(status.file_name, f"[red]{status.error}[/]", "-", "-", "-", "[red]?[/]")
        elif status.info is None:
            table.add_row(status.file_name, "-", "-", "-", "-", "[yellow]não cadastrada[/]")
        else:
            days = status.info.days_to_expire()
            table.add_row(
                status.file_name,
                status.info.holder_name,
                format_cnpj(status.info.cnpj) if status.info.cnpj else "-",
                f"{status.info.not_after:%d/%m/%Y}",
                f"[{_expiry_style(days)}]{days}[/]",
                "[green]ok[/]",
            )
    console.print(table)


@cert_app.command("remove")
def cert_remove(
    name: Annotated[str, typer.Argument(help="Nome do arquivo em certs/ (ex.: madison.pfx).")],
) -> None:
    """Remove a senha do certificado do cofre do sistema (o arquivo é mantido)."""
    try:
        removed = forget_password(name)
    except CredentialStoreError as exc:
        raise _fail(str(exc)) from exc
    if removed:
        console.print(f"Senha de {name} removida do cofre do sistema.")
    else:
        console.print(f"[yellow]Nenhuma senha cadastrada para {name}.[/]")


# --- config ------------------------------------------------------------------------------


@config_app.command("sync")
def config_sync() -> None:
    """Acrescenta à planilha os condomínios dos certificados de certs/ ainda não listados."""
    settings = get_settings()
    try:
        summary = sync_from_certificates(settings)
    except ConfigError as exc:
        raise _fail(f"planilha inválida: {exc}") from exc
    except CredentialStoreError as exc:
        raise _fail(str(exc)) from exc
    for added in summary.added:
        state = "ativo" if added.active else "[yellow]inativo (verificar)[/]"
        console.print(
            f"[green]+[/] {added.name} ({added.cnpj_formatted}) — {added.certificate} — {state}"
        )
    for updated in summary.updated:
        console.print(f"[cyan]~[/] {updated.name}: certificado → {updated.certificate}")
    for skipped in summary.skipped:
        console.print(
            f"[yellow]![/] {skipped}: senha não cadastrada ou sem CNPJ "
            f"(condosys cert add certs/{skipped})"
        )
    if not (summary.added or summary.updated):
        console.print("Nada a acrescentar.")
    console.print(f"Planilha: {settings.config_file}")


def _check_row(settings: Settings, condominium: Condominium, today: date) -> tuple[str, str]:
    """Returns (status markup, message) for one condominium."""
    try:
        status = certificate_status(settings, condominium.certificate)
    except CredentialStoreError as exc:
        return "[red]ERRO[/]", str(exc)
    if status.error:
        return "[red]ERRO[/]", status.error
    if status.info is None:
        return (
            "[red]ERRO[/]",
            f"senha não cadastrada (condosys cert add certs/{condominium.certificate})",
        )
    info = status.info
    problems: list[str] = []
    warnings: list[str] = []
    days = info.days_to_expire(today)
    if days < 0:
        problems.append(f"certificado vencido em {info.not_after:%d/%m/%Y}")
    elif days < EXPIRY_WARNING_DAYS:
        warnings.append(f"certificado vence em {days} dias")
    if info.cnpj is None:
        problems.append("certificado sem CNPJ (o ADN exige e-CNPJ)")
    elif not same_cnpj_root(info.cnpj, condominium.cnpj):
        problems.append(f"o certificado é de {format_cnpj(info.cnpj)} ({info.holder_name})")

    message = "; ".join([*problems, *warnings, info.holder_name])
    if problems:
        return "[red]ERRO[/]", message
    if warnings:
        return "[yellow]ALERTA[/]", message
    return "[green]OK[/]", message


@config_app.command("check")
def config_check() -> None:
    """Valida condominios.xlsx e cruza com os certificados (o CNPJ tem de bater)."""
    settings = get_settings()
    condominiums = _load_condominiums(settings)
    table = Table(title=f"{settings.config_file.name}: {len(condominiums)} condomínios")
    for column in ("Linha", "Ativo", "Nome", "CNPJ", "Certificado", "Status", "Detalhe"):
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
            condominium.certificate,
            status,
            message,
        )
    console.print(table)
    if has_error:
        raise _fail("há condomínios ativos com problemas.")
    console.print("[green]Configuração válida.[/]")


# --- notas / coletar ---------------------------------------------------------------------


def _print_invoices(result: RunResult, competence: Competence) -> None:
    table = Table(title=f"{result.condominium_name} — notas tomadas em {competence.label}")
    money = ("Valor", "ISS retido", "INSS", "IRRF", "CSLL/PCC", "Líquido")
    for column in ("Nº", "Emissão", "Prestador", "Serviço", *money):
        table.add_column(column, justify="right" if column in money else "left")
    for invoice in result.invoices:
        table.add_row(
            invoice.number,
            f"{invoice.issue_date:%d/%m/%Y}",
            f"{invoice.provider_name[:30]} ({format_cnpj(invoice.provider_document)})",
            invoice.service_code or "-",
            _brl(invoice.amount),
            _brl(invoice.iss_withheld),
            _brl(invoice.inss),
            _brl(invoice.irrf),
            _brl(invoice.social_contributions_withheld),
            _brl(invoice.net_amount),
        )
    console.print(table)


@app.command()
def notas(
    condominio: Annotated[str, typer.Argument(help="Nome (ou parte do nome) ou CNPJ.")],
    competencia: Annotated[
        str, typer.Option("--competencia", "-c", help="MM/AAAA (ex.: 09/2026).")
    ],
    sem_sincronizar: Annotated[
        bool, typer.Option("--sem-sincronizar", help="Usa só o que já foi baixado.")
    ] = False,
) -> None:
    """Lista as notas tomadas por um condomínio na competência (API do ADN)."""
    settings = get_settings()
    competence = _parse_competence(competencia)
    condominium = resolve_condominium(settings, condominio)
    result = collect_condominium(
        settings,
        condominium,
        competence,
        sync=not sem_sincronizar,
        on_phase=lambda message: console.print(f"[dim]{message}[/]"),
    )
    if not result.success:
        raise _fail(result.error or "falha na coleta")
    _print_invoices(result, competence)
    console.print(f"{len(result.invoices)} notas.")


@app.command()
def coletar(
    competencia: Annotated[
        str, typer.Option("--competencia", "-c", help="MM/AAAA (ex.: 09/2026).")
    ],
    condominio: Annotated[
        list[str] | None,
        typer.Option("--condominio", help="Só estes condomínios (pode repetir)."),
    ] = None,
    sem_sincronizar: Annotated[
        bool, typer.Option("--sem-sincronizar", help="Usa só o que já foi baixado.")
    ] = False,
) -> None:
    """Coleta as notas tomadas de todos os condomínios ativos e gera o Excel em output/."""
    settings = get_settings()
    competence = _parse_competence(competencia)
    if condominio:
        targets = [resolve_condominium(settings, query) for query in condominio]
    else:
        try:
            targets = active_condominiums(settings)
        except ConfigError as exc:
            raise _fail(f"planilha inválida: {exc}") from exc
    if not targets:
        raise _fail("nenhum condomínio ativo na planilha.")

    def progress(index: int, total: int, condominium: Condominium, message: str) -> None:
        console.print(f"[dim][{index}/{total}] {condominium.name}: {message}[/]")

    results = collect_all(
        settings, targets, competence, sync=not sem_sincronizar, progress=progress
    )
    output = export_results(
        results, competence, build_output_path(settings.output_dir, competence, datetime.now())
    )

    table = Table(title=f"Coleta {competence.label}")
    for column in ("Condomínio", "Situação", "Notas", "Valor total"):
        table.add_column(column)
    for result in results:
        table.add_row(
            result.condominium_name,
            "[green]OK[/]" if result.success else f"[red]ERRO[/] {result.error}",
            str(len(result.invoices)),
            _brl(sum((i.amount for i in result.invoices), Decimal("0"))),
        )
    console.print(table)
    console.print(f"Planilha gerada: [bold]{output}[/]")
    if any(not r.success for r in results):
        raise typer.Exit(1)


# --- ADN diagnostics --------------------------------------------------------------------------


def _adn_target(
    settings: Settings, condominio: str | None, cert: str | None
) -> tuple[LoadedCertificate, str, str | None]:
    """Returns (certificate, CNPJ to query, cnpjConsulta) for the ADN diagnostics."""
    cnpj: str | None = None
    if condominio is not None:
        condominium = resolve_condominium(settings, condominio)
        certificate_file, cnpj = condominium.certificate, condominium.cnpj
    elif cert is not None:
        certificate_file = cert
    else:
        raise _fail("informe o condomínio ou --cert <arquivo.pfx>.")
    try:
        password = get_password(certificate_file)
    except CredentialStoreError as exc:
        raise _fail(str(exc)) from exc
    if password is None:
        raise _fail(f"senha de {certificate_file} não cadastrada (condosys cert add).")
    try:
        loaded = load_pfx(settings.certs_dir / certificate_file, password)
    except CertificateError as exc:
        raise _fail(str(exc)) from exc
    if loaded.info.cnpj is None:
        raise _fail(f"{certificate_file} não tem CNPJ (o ADN exige e-CNPJ).")
    if cnpj is not None and not same_cnpj_root(cnpj, loaded.info.cnpj):
        raise _fail(
            f"o ADN só aceita certificado com a mesma raiz de CNPJ do consultado; "
            f"{certificate_file} é de {loaded.info.holder_name}."
        )
    target = cnpj or loaded.info.cnpj
    return loaded, target, cnpj if cnpj != loaded.info.cnpj else None


@app.command("adn-test")
def adn_test(
    condominio: Annotated[
        str | None, typer.Argument(help="Condomínio. Omitido: use --cert.")
    ] = None,
    cert: Annotated[
        str | None,
        typer.Option(
            "--cert", help="Certificado em certs/ (consulta o CNPJ do próprio certificado)."
        ),
    ] = None,
    nsu: Annotated[int, typer.Option("--nsu", help="NSU inicial (0 = desde o início).")] = 0,
) -> None:
    """Faz UMA consulta à API de distribuição do ADN e salva a resposta em debug/adn/."""
    settings = get_settings()
    loaded, target, cnpj_query = _adn_target(settings, condominio, cert)
    console.print(
        f"ADN: consultando {format_cnpj(target)} com {loaded.info.holder_name}, NSU {nsu}..."
    )
    try:
        response = fetch_dfe(settings.adn_base_url, loaded, nsu, cnpj=cnpj_query)
    except AdnError as exc:
        raise _fail(str(exc)) from exc

    out_dir = settings.debug_dir / "adn" / f"{datetime.now():%Y%m%d-%H%M%S}"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "resposta.txt").write_text(response.text, encoding="utf-8")
    documents = decode_documents(response.payload)
    for number, xml in enumerate(documents, start=1):
        (out_dir / f"{number:03d}.xml").write_text(xml, encoding="utf-8")

    table = Table(show_header=False, box=None)
    table.add_row("HTTP", str(response.status_code))
    table.add_row("URL", response.url.split("?")[0])
    if isinstance(response.payload, dict):
        table.add_row("Campos", ", ".join(map(str, response.payload)))
    table.add_row("Documentos XML", str(len(documents)))
    table.add_row("Salvo em", str(out_dir))
    console.print(table)
    if response.status_code >= 400:
        console.print(f"[yellow]Resposta do ADN:[/] {response.text[:500]}")
        raise typer.Exit(1)


# --- local API for the desktop app --------------------------------------------------------


@app.command()
def serve(
    port: Annotated[
        int | None, typer.Option("--port", help="Porta (0 = escolher uma livre).")
    ] = None,
) -> None:
    """Inicia a API local usada pela interface (Electron). Só aceita conexões locais."""
    from condosys.api import run_server

    settings = get_settings()
    run_server(settings, port=settings.api_port if port is None else port)
