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

# --- Header (after login) ----------------------------------------------------------------

# TODO: capturar via recon — element with the current taxpayer name / CNPJ.
HEADER_TAXPAYER: str | None = None

# TODO: capturar via recon — element with the current competence.
HEADER_COMPETENCE: str | None = None

# --- Empresas (default/empresas.aspx) — company selection after a proxy login ------------
# PROVISÓRIO: texts seen on screenshots of 23/10/2026 (docs/issnet-mapa.md, 1.1); no HTML
# captured yet. The locators are built from these texts in session.py; replace them with
# real ids once the recon captures this screen.

COMPANY_SELECTION_URL_PART = "empresas.aspx"  # confirmed (URL after the proxy login)
COMPANY_FILTER_CNPJ_LABEL = "CPF / CNPJ"
# The search button shows the tooltip "Localizar"; it is the first button after "Ano".
COMPANY_SEARCH_TITLE = "Localizar"
COMPANY_SEARCH_AFTER_LABEL = "Ano"
# Last clickable element of the grid row ("Selecione" column, green ✓).
COMPANY_ROW_SELECT = "a, button, input[type=submit], input[type=image], input[type=button]"

# TODO: capturar via recon — logout link/button.
LOGOUT_BUTTON: str | None = None

# --- Menu -> Declaração de Serviços Contratados -> Consulta de Notas Tomadas -------------

# PROVISÓRIO: visible menu texts (rotina-fiscal.pdf, 4.6, and the menu screenshot of
# 23/10/2026: "≡ Menu" button, "Buscar no Menu IssNet" search, expandable items).
MENU_TEXT = "Menu"
MENU_CONTRACTED_SERVICES_TEXT = "Declaração de Serviços Contratados"
MENU_TAKEN_INVOICES_TEXT = "Consulta de Notas Tomadas"
# Text expected on the "Consulta Notas Tomadas" screen (rotina-fiscal.pdf, 4.6).
TAKEN_INVOICES_PAGE_TEXT = "Notas Tomadas"

# TODO: capturar via recon — direct URL of "Consulta Notas Tomadas", if stable.
TAKEN_INVOICES_URL: str | None = None

# --- Consulta Notas Tomadas: filters -----------------------------------------------------

# TODO: capturar via recon — "Série" select and the option value for NFS-e.
FILTER_SERIES: str | None = None
FILTER_SERIES_NFSE_LABEL = "Nota Fiscal de Serviço Eletrônica - NFS-e"  # PROVISÓRIO

# TODO: capturar via recon — "Filtros Adicionais" expander (the ▽ button).
FILTER_ADDITIONAL_TOGGLE: str | None = None

# TODO: capturar via recon — date inputs (check the expected format, probably dd/mm/aaaa).
FILTER_ISSUE_DATE_START: str | None = None
FILTER_ISSUE_DATE_END: str | None = None

# TODO: capturar via recon — "Status NFS-e" select ("Normal" / "Cancelado").
FILTER_STATUS: str | None = None
FILTER_STATUS_NORMAL_LABEL = "Normal"  # PROVISÓRIO

# TODO: capturar via recon — "Localizar" button.
FILTER_SEARCH_BUTTON: str | None = None

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
