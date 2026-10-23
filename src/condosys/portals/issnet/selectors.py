"""Every ISSNet selector lives here, and only here.

Rules:
    * Never invent a selector. Values marked ``TODO: capturar via recon`` must be filled
      from the HTML saved by ``condosys recon`` (``debug/recon/<timestamp>/``) and
      documented in ``docs/issnet-mapa.md``.
    * Values marked ``PROVISÓRIO`` come from the visible texts described in
      ``docs/rotina-fiscal.pdf``; confirm them against the recon HTML.

How to capture a selector:
    1. Run ``uv run condosys recon "<condomínio>"``.
    2. In the Playwright Inspector, click "Pick locator" and hover the element.
    3. Prefer stable ``id`` attributes (ASP.NET ids such as ``ctl00_..._btnX``) or
       role + accessible name; avoid positional XPath.
    4. Copy the locator here and record the screen in ``docs/issnet-mapa.md``.
"""

# --- Login (Login.aspx) ------------------------------------------------------------------
# Confirmed on 2026-10-22 from the public login page (see docs/issnet-mapa.md, section 1).
# Flow: the button calls btnAssinar_onClick() → ihubauth(<#licencaCertificado>) opens a
# popup at https://api.ihub.com.br/auth, where the browser presents the certificate in the
# TLS handshake; the popup posts a ticket back, which goes to #ticketcertificado and is
# submitted with __doPostBack('btnToken').

LOGIN_CERTIFICATE_BUTTON = "#btnAcionaCertificado"
LOGIN_CERTIFICATE_BUTTON_TEXT = "Logar com certificado digital"
# Global JS function defined by ihubauth.js; missing when the portal scripts were blocked.
LOGIN_AUTH_FUNCTION = "ihubauth"
# Confirmed on 2026-10-23 (real login): the iHub popup may show a Cloudflare Turnstile
# checkbox ("Confirme que é humano"), served in an iframe from this host. A person must
# tick it; the login waits for them (settings.human_check_timeout_ms).
HUMAN_CHECK_FRAME_URL = "challenges.cloudflare.com"

# TODO: capturar via recon — URL (or URL fragment) that only exists after a successful login.
LOGGED_IN_URL_PATTERN: str | None = None

# TODO: capturar via recon — message element shown when the login fails.
LOGIN_ERROR_MESSAGE: str | None = None

# --- Shell after the company is chosen (Default/Master.aspx) ----------------------------
# Confirmed on 23/10/2026 from the real HTML (debug/falha-empresa_20261023-004227.html).
# Master.aspx is a shell: header + Telerik menu; every screen opens inside the iframe below.

CONTENT_FRAME_NAME = "iframe"  # <iframe id="iframe" name="iframe" src="Default.aspx">
HEADER_COMPANY_NAME = "#lblNomeEmpresa"  # selected taxpayer name (no CNPJ in the header)
HEADER_MUNICIPAL_REGISTRATION = "#lblCae"
HEADER_USER_NAME = "#lblNomeUsuario"  # certificate holder (e.g. Sema Contabilidade)
# "Alterar Empresa": back to the Empresas screen without a new login. Hidden inside the
# collapsed navbar (☰) — trigger with __doPostBack('btnEmpresas','') or open the navbar.
CHANGE_COMPANY_BUTTON = "#btnEmpresas"
LOGOUT_BUTTON = "#btnSair"

# Kept for compatibility: the header shows the name, not the CNPJ.
HEADER_TAXPAYER: str | None = None

# TODO: capturar via recon — element with the current competence.
HEADER_COMPETENCE: str | None = None

# --- Empresas (default/empresas.aspx) — company selection after a proxy login ------------
# PROVISÓRIO: texts seen on screenshots of 23/10/2026 (docs/issnet-mapa.md, 1.1); no HTML
# captured yet. The locators are built from these texts in session.py; replace them with
# real ids once the recon captures this screen.

# Confirmed: /online/default/empresas.aspx after login, /online/Default/Empresas.aspx from
# "Alterar Empresa" (compare in lower case).
COMPANY_SELECTION_URL_PART = "empresas.aspx"
COMPANY_FILTER_CNPJ_LABEL = "CPF / CNPJ"
# The search button shows the tooltip "Localizar" (else: Enter in the CNPJ field).
COMPANY_SEARCH_TITLE = "Localizar"
# Last clickable element of the grid row ("Selecione" column, green ✓).
COMPANY_ROW_SELECT = "a, button, input[type=submit], input[type=image], input[type=button]"


# --- Menu -> Declaração de Serviços Contratados -> Consulta de Notas Tomadas -------------
# Confirmed (real HTML): Telerik tree, <a class="rtIn" target="iframe"
# href="../NotaDigital/ConsultaNotaTomador.aspx">Consulta de Notas Tomadas</a>. condosys
# loads that address in the content iframe, exactly as the menu link does.

MENU_TEXT = "Menu"
MENU_CONTRACTED_SERVICES_TEXT = "Declaração de Serviços Contratados"
MENU_TAKEN_INVOICES_TEXT = "Consulta de Notas Tomadas"
TAKEN_INVOICES_PATH = "/online/NotaDigital/ConsultaNotaTomador.aspx"
# PROVISÓRIO: text expected on the "Consulta Notas Tomadas" screen (rotina-fiscal.pdf, 4.6).
TAKEN_INVOICES_PAGE_TEXT = "Notas Tomadas"

# --- Consulta Notas Tomadas: filters ----------------------------------------------------
# Confirmed on 23/10/2026 from the real HTML of /online/NotaDigital/ConsultaNotaTomador.aspx
# (inside the content iframe). ASP.NET postbacks: links call __doPostBack.

FILTER_SERIES = "#ddlSerie"
FILTER_SERIES_NFSE_VALUE = "1"  # "Nota Fiscal de Serviço Eletrônica - NFS-e"
# Other options: "2" NFSA-e avulsa, "20" "NFS-e - Modelo Nacional" (DF national standard is
# mandatory from 01/10/2026 — the query may need this series for 10/2026 on), "24" restaurada.
FILTER_SERIES_NATIONAL_VALUE = "20"
FILTER_SERIES_NFSE_LABEL = "Nota Fiscal de Serviço Eletrônica - NFS-e"
FILTER_NUMBER_START = "#txtNumIni"
FILTER_NUMBER_END = "#txtNumFinal"

# "Filtros Adicionais" ▽: postback that shows #trDadosDocumento / #trStatusNota.
FILTER_ADDITIONAL_TOGGLE = "#imbArrow"
FILTER_ADDITIONAL_PANEL = "#trDadosDocumento"

# dd/mm/aaaa, maxlength 10, formatted by FormataData on keypress (type it, do not paste).
FILTER_ISSUE_DATE_START = "#txtDtEmissaoIni"
FILTER_ISSUE_DATE_END = "#txtDtEmissaoFim"
FILTER_PROVIDER_DOCUMENT = "#txtCpfCnpjPrestador"

# Changing the status triggers a postback (onchange __doPostBack('ddlStatusNfse')).
FILTER_STATUS = "#ddlStatusNfse"
FILTER_STATUS_NORMAL_VALUE = "1"  # "2" = Cancelado
FILTER_STATUS_NORMAL_LABEL = "Normal"
FILTER_NATURE = "#ddlNatOperacao"

FILTER_SEARCH_BUTTON = "#btnBuscarNotas"  # "Localizar"
PRINT_BUTTON = "#btnImprimir"

# --- Consulta Notas Tomadas: "Documentos Fiscais" grid -----------------------------------

# TODO: capturar via recon — grid table, its data rows and the pager.
RESULTS_TABLE: str | None = None
RESULTS_ROWS: str | None = None
RESULTS_PAGER_NEXT: str | None = None
RESULTS_EMPTY_MESSAGE: str | None = None

# TODO: capturar via recon — per-row buttons (Visualizar, document icon — XML/PDF?, Imprimir).
ROW_VIEW_BUTTON: str | None = None
ROW_DOCUMENT_BUTTON: str | None = None
ROW_PRINT_BUTTON: str | None = None
