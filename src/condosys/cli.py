"""Command line interface (Typer)."""

import contextlib
import logging
import re
import shutil
import unicodedata
from datetime import date, datetime
from pathlib import Path
from typing import Annotated

import typer
from playwright.sync_api import BrowserContext
from playwright.sync_api import Error as PlaywrightError
from rich.console import Console
from rich.table import Table

from condosys import __version__
from condosys.adn import AdnError, decode_documents, fetch_dfe, same_cnpj_root
from condosys.assisted_browser import AssistedLoginError
from condosys.browser import BrowserSetupError
from condosys.cert_store import CertStoreError, install_certificate
from condosys.certificates import (
    CertificateError,
    list_certificate_files,
    load_pfx,
    read_certificate_info,
)
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
from condosys.portals.issnet import selectors
from condosys.portals.issnet.invoices_page import TakenInvoicesPage
from condosys.portals.issnet.session import (
    IssnetSession,
    LoginError,
    NavigationError,
    issnet_session,
    needs_taxpayer_selection,
)
from condosys.recon import PageRecorder, new_recon_dir
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


@cert_app.command("install")
def cert_install(
    name: Annotated[str, typer.Argument(help="Nome do arquivo em certs/ (ex.: sema.pfx).")],
) -> None:
    """Instala o certificado no Chrome/Edge deste usuário (para o login assistido)."""
    settings = get_settings()
    path = settings.certs_dir / name
    if not path.is_file():
        raise _fail(f"{path} não existe. Cadastre antes com: condosys cert add <arquivo>")
    try:
        password = get_password(name)
    except CredentialStoreError as exc:
        raise _fail(str(exc)) from exc
    if password is None:
        raise _fail(f"senha de {name} não cadastrada. Rode: condosys cert add certs/{name}")
    try:
        info = read_certificate_info(path, password)
        where = install_certificate(path, password)
    except (CertificateError, CertStoreError) as exc:
        raise _fail(str(exc)) from exc
    console.print(f"[green]Certificado instalado:[/] {info.holder_name}")
    console.print(f"Local: {where}")
    console.print("Feche e abra o navegador para ele aparecer na lista de certificados.")


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


# --- login-test / recon ------------------------------------------------------------------


def _file_slug(text: str) -> str:
    plain = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r"[^0-9A-Za-z]+", "-", plain).strip("-").lower()[:40] or "condominio"


IHUB_BLOCK_NOTICE = (
    "Automação do portal ISSNet desativada. Em 23/10/2026 o iHub (login do portal) "
    'respondeu: "Acesso automatizado deve usar o webservice do sistema. Se o uso é '
    'legítimo, informe ao suporte o código a seguir. Ref.: 568F9D19". O condosys não '
    "contorna esse bloqueio (docs/decisoes.md, ADR-010). Caminhos: API do ADN para acesso "
    "DIRETO (condosys adn-test) e contato com o suporte do ISSNet sobre o webservice. Só "
    "use CONDOSYS_ISSNET_AUTOMATION_AUTHORIZED=true se o suporte autorizar por escrito."
)


def _ensure_portal_automation_allowed(settings: Settings) -> None:
    if not settings.issnet_automation_authorized:
        raise _fail(IHUB_BLOCK_NOTICE)


def _describe(settings: Settings, condominium: Condominium) -> None:
    console.print(
        f"Condomínio: [bold]{condominium.name}[/] ({condominium.cnpj_formatted}) — "
        f"acesso {condominium.access_mode.value} com certs/{condominium.certificate}"
    )
    if settings.login_mode != "assisted":
        return
    holder = condominium.certificate
    try:
        password = get_password(condominium.certificate)
        if password is not None:
            info = read_certificate_info(settings.certs_dir / condominium.certificate, password)
            holder = f"{info.holder_name} ({format_cnpj(info.cnpj) if info.cnpj else '-'})"
    except (CredentialStoreError, CertificateError):
        pass
    console.print(
        "\n[bold]Login assistido[/] — na janela do navegador que vai abrir:\n"
        "  1. clique em [bold]Logar com certificado digital[/];\n"
        f"  2. escolha o certificado [bold]{holder}[/];\n"
        "  3. se aparecer [bold]Confirme que é humano[/], marque a caixa.\n"
        "Quando o portal abrir, o condosys assume sozinho. "
        f"(Aguardando até {settings.assisted_login_timeout_ms // 1000} s.)\n"
    )


def _select_company(session: IssnetSession, condominium: Condominium, interactive: bool) -> None:
    """Selects the condominium on the "Empresas" screen, falling back to a manual step."""
    if not session.on_company_selection():
        if needs_taxpayer_selection(condominium):
            logger.warning("Procuração, mas o portal não abriu a tela Empresas.")
        return
    try:
        session.select_company(condominium)
        return
    except NavigationError as exc:
        if not interactive:
            raise _fail(str(exc)) from exc
        console.print(f"\n[bold yellow]Não consegui selecionar a empresa sozinho:[/] {exc}")
    console.print(
        f"[bold yellow]Passo manual:[/] na tela Empresas, filtre pelo CNPJ "
        f"{condominium.cnpj_formatted} e clique no ✓ de {condominium.name}."
    )
    console.input("Depois de selecionar, pressione [bold]Enter[/] aqui... ")


def _open_taken_invoices(settings: Settings, session: IssnetSession, interactive: bool) -> bool:
    """Opens "Consulta de Notas Tomadas"; returns whether the screen is open."""
    page = TakenInvoicesPage(session.page, settings.debug_dir)
    try:
        page.open()
        return True
    except NavigationError as exc:
        console.print(f"\n[bold yellow]Não consegui abrir Consulta de Notas Tomadas:[/] {exc}")
        if not interactive:
            return False
    console.print(
        "[bold yellow]Passo manual:[/] abra Menu → Declaração de Serviços Contratados → "
        "Consulta de Notas Tomadas."
    )
    console.input("Depois de abrir, pressione [bold]Enter[/] aqui... ")
    text, _ = session.identity_text()  # text of every frame (the screen opens in an iframe)
    return selectors.TAKEN_INVOICES_PAGE_TEXT in text


@app.command("login-test")
def login_test(
    condominio: Annotated[str, typer.Argument(help="Nome (ou parte do nome) ou CNPJ.")],
    headless: Annotated[
        bool, typer.Option("--headless", help="Não mostra a janela do navegador.")
    ] = False,
) -> None:
    """Faz login no ISSNet com o certificado do condomínio e confere o ambiente."""
    settings = get_settings()
    _ensure_portal_automation_allowed(settings)
    condominium = resolve_condominium(settings, condominio)
    _describe(settings, condominium)
    stamp = f"{datetime.now():%Y%m%d-%H%M%S}"
    base_name = f"login-test_{_file_slug(condominium.name)}_{stamp}"

    try:
        with issnet_session(settings, condominium, headless=headless) as session:
            try:
                session.login()
            except LoginError:
                shot = session.screenshot(settings.debug_dir / f"{base_name}_erro.png")
                console.print(f"Screenshot do erro: {shot}")
                raise
            _select_company(session, condominium, interactive=not headless)
            check = session.check_identity(condominium)
            invoices_open = _open_taken_invoices(settings, session, interactive=not headless)
            shot = session.screenshot(settings.debug_dir / f"{base_name}.png")
            title = session.page.title()
            url = session.page.url
    except (BrowserSetupError, AssistedLoginError, LoginError, CredentialStoreError) as exc:
        raise _fail(str(exc)) from exc
    except PlaywrightError as exc:
        raise _fail(f"erro no navegador: {exc}") from exc

    table = Table(show_header=False, box=None)
    table.add_row("Página", title)
    table.add_row("URL", url.split("?")[0])
    table.add_row(
        f"CNPJ na página ({check.source})",
        "[green]sim[/]" if check.cnpj_found else "[red]não[/]",
    )
    if check.header_name:
        match = "[green]confere[/]" if check.selected_company_match else "[yellow]?[/]"
        table.add_row("Empresa no cabeçalho", f"{check.header_name} ({match})")
    table.add_row("Nome na página", "[green]sim[/]" if check.name_found else "[yellow]não[/]")
    table.add_row(
        "Consulta de Notas Tomadas", "[green]aberta[/]" if invoices_open else "[red]não abriu[/]"
    )
    table.add_row("Screenshot", str(shot))
    console.print(table)
    if not check.confirmed:
        console.print(
            "[bold yellow]Login feito, mas o CNPJ do condomínio não apareceu na página.[/] "
            "Confira o screenshot; rode o recon para mapear o cabeçalho."
        )
        raise typer.Exit(2)
    if not invoices_open:
        raise typer.Exit(3)
    console.print(
        "[bold green]Login confirmado no ambiente do condomínio e "
        "Consulta de Notas Tomadas aberta.[/]"
    )


def _wait_until_closed(context: BrowserContext, recorder: PageRecorder) -> None:
    """Keeps the recorder running until every tab is closed."""
    while True:
        pages = [page for page in context.pages if not page.is_closed()]
        if not pages:
            return
        with contextlib.suppress(PlaywrightError):
            pages[-1].wait_for_timeout(500)
        recorder.flush()


@app.command()
def recon(
    condominio: Annotated[str, typer.Argument(help="Nome (ou parte do nome) ou CNPJ.")],
    trace: Annotated[
        bool,
        typer.Option(
            "--trace",
            help="Grava também um trace do Playwright (trace.zip). Contém cookies da sessão.",
        ),
    ] = False,
) -> None:
    """Faz login e abre o Playwright Inspector, salvando HTML + screenshot de cada tela."""
    settings = get_settings()
    _ensure_portal_automation_allowed(settings)
    condominium = resolve_condominium(settings, condominio)
    _describe(settings, condominium)
    out_dir = new_recon_dir(settings.debug_dir)
    recorder = PageRecorder(out_dir)
    contexts: list[BrowserContext] = []

    def on_context(context: BrowserContext) -> None:
        contexts.append(context)
        recorder.attach(context)
        if trace:
            context.tracing.start(screenshots=True, snapshots=True)

    login_failed = False
    try:
        with issnet_session(
            settings, condominium, headless=False, on_context=on_context
        ) as session:
            try:
                session.login()
            except LoginError as exc:
                login_failed = True
                console.print(f"[bold red]Login falhou:[/] {exc}")
                console.print("O Inspector vai abrir mesmo assim para investigar a tela.")
            if session.assisted:
                # The pages before the takeover were not recorded; save the current one.
                recorder.capture(session.page, "inicial")
            if not login_failed:
                # The automatic steps are recorded too (Empresas filter, menu, query screen).
                _select_company(session, condominium, interactive=True)
                _open_taken_invoices(settings, session, interactive=False)
            console.print(
                "\n[bold]Recon em andamento[/]\n"
                f"  - Tudo é salvo em {out_dir}\n"
                "  - Cada página carregada é capturada automaticamente.\n"
                "  - Use o botão [bold]Capturar[/] (canto inferior direito) após filtros e\n"
                "    atualizações parciais (ex.: depois de clicar em Localizar).\n"
                "  - No Inspector, 'Pick locator' mostra o seletor de um elemento.\n"
                "  - Clique em 'Resume' (▶) no Inspector para continuar navegando sem ele;\n"
                "    feche todas as abas do navegador para terminar."
            )
            session.page.pause()
            recorder.flush()
            console.print("Inspector retomado. Feche as abas do navegador para terminar.")
            _wait_until_closed(session.page.context, recorder)
            if trace:
                try:
                    session.page.context.tracing.stop(path=out_dir / "trace.zip")
                    console.print(
                        f"Trace salvo: {out_dir / 'trace.zip'} "
                        "(abra com: uv run playwright show-trace <arquivo>)"
                    )
                except PlaywrightError as exc:
                    console.print(f"[yellow]Não foi possível salvar o trace:[/] {exc}")
    except (BrowserSetupError, AssistedLoginError, CredentialStoreError) as exc:
        raise _fail(str(exc)) from exc
    except PlaywrightError as exc:
        # Closing the browser window while paused ends the session abruptly.
        logger.debug("Sessão do navegador encerrada: %s", exc)
        recorder.flush()

    console.print(f"\n[bold]{recorder.count} capturas[/] em {out_dir}")
    console.print(
        "Próximo passo: preencha docs/issnet-mapa.md e "
        "src/condosys/portals/issnet/selectors.py a partir desse material."
    )
    if login_failed:
        raise typer.Exit(1)


# --- ADN (national NFS-e data environment) -------------------------------------------------


@app.command("adn-test")
def adn_test(
    condominio: Annotated[
        str | None,
        typer.Argument(help="Condomínio (acesso DIRETO). Omitido: use --cert."),
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
    if cnpj is not None and (
        loaded.info.cnpj is None or not same_cnpj_root(cnpj, loaded.info.cnpj)
    ):
        raise _fail(
            f"o ADN só aceita certificado com a mesma raiz de CNPJ do consultado. "
            f"{certificate_file} é de {loaded.info.holder_name}; para condomínios por "
            "procuração use o portal (login assistido)."
        )

    target = format_cnpj(cnpj or loaded.info.cnpj or "-")
    console.print(f"ADN: consultando {target} com {loaded.info.holder_name}, NSU {nsu}...")
    try:
        response = fetch_dfe(settings.adn_base_url, loaded, nsu, cnpj=cnpj)
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
