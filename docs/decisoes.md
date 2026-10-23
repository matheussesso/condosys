# Registro de decisões técnicas

Formato simples de ADR: contexto, decisão, consequências. Mais recentes no fim.

## ADR-001 — Stack base (Fase 0)

- **Contexto:** sistema usado em Windows pelos funcionários e desenvolvido em Linux.
- **Decisão:** Python 3.12+ com uv (`pyproject.toml`, `uv.lock`, `.python-version` = 3.12),
  layout `src/`; Typer + Rich (CLI), Pydantic v2 + pydantic-settings, openpyxl, keyring,
  cryptography, Playwright (API síncrona); pytest, ruff, mypy strict.
- **Consequências:** `uv sync` reproduz o ambiente nos dois sistemas; o uv baixa o Python.

## ADR-002 — Autenticação via `client_certificates` do Playwright (Fase 0/1)

- **Contexto:** hoje o login exige escolher o certificado numa janela do Edge e fechar o
  navegador para trocar de certificado.
- **Verificação na documentação oficial** (playwright.dev/python, `Browser.new_context`):
  `client_certificates` é uma lista de dicionários com `origin` (obrigatório, só
  `esquema://host[:porta]`), e uma das formas: `certPath`+`keyPath`, `cert`+`key` (bytes),
  `pfxPath` ou `pfx` (bytes), mais `passphrase` opcional. Recurso adicionado na
  **v1.46**; `cert`/`key`/`pfx` em memória na **v1.47**. Confirmado no pacote instalado
  (1.64.1, `playwright/_impl/_api_structures.py: ClientCertificate`). Exigimos `playwright>=1.47`.
- **Decisão:** um `BrowserContext` novo por certificado. O `.pfx` é aberto com
  `cryptography` e reserializado **em memória** (AES-256) e passado como `pfx` (bytes) +
  `passphrase`. Desligável com `CONDOSYS_REENCODE_PFX=false` (passa `pfxPath` direto).
- **Por que recodificar:** muitos A1 de ACs brasileiras vêm cifrados com RC2/3DES; o
  OpenSSL 3 usado pelo navegador/driver costuma recusar esses PKCS#12 ("unsupported").
  Recodificar evita isso sem gravar nada em disco.
- **Origens:** `CONDOSYS_ISSNET_CERT_ORIGINS` (padrão `https://iss.fazenda.df.gov.br`). Se
  o recon mostrar que "Logar com certificado digital" vai para outro host/porta, basta
  incluir a origem nessa lista.

### Plano B (se o `client_certificates` falhar no ISSNet)

Não forçar soluções frágeis. Registrar aqui o erro exato e seguir, nesta ordem:

1. Ajustar a `origin`/rota do certificado (ver `debug/recon/*/requests.log`) ou usar
   `CONDOSYS_BROWSER_CHANNEL=msedge`/`chrome`.
2. Login por HTTP puro (`httpx` ou `requests` + `requests-pkcs12`) e reaproveitar os
   cookies no contexto do Playwright (`context.add_cookies`).
3. Chromium com a política `AutoSelectCertificateForUrls` e o certificado instalado no
   repositório do sistema (somente Windows).

## ADR-003 — Senhas no keyring

- **Decisão:** senha de cada `.pfx` no cofre do sistema (serviço `condosys`, conta
  `pfx:<nome-do-arquivo>` em minúsculas). Nunca em arquivo, `.env`, código ou log.
  `keyrings.alt` (arquivo em texto) **não** é usado.
- **Consequências:** cada computador cadastra as senhas uma vez (`condosys cert add`). No
  Linux é preciso GNOME Keyring/KWallet desbloqueado; sem ele o comando explica o erro.

## ADR-004 — CNPJ alfanumérico

- **Contexto:** a IN RFB 2.229/2024 introduz CNPJs alfanuméricos a partir de julho/2026;
  prestadores novos podem já ter esse formato.
- **Decisão:** normalização = remover pontuação e passar para maiúsculas (não "só
  dígitos"). Dígitos verificadores calculados com o valor ASCII − 48 de cada caractere
  (compatível com o CNPJ numérico). Inteiros vindos do Excel recebem zeros à esquerda.

## ADR-005 — Planilha de condomínios

- **Decisão:** `config/condominios.xlsx` (colunas `ativo`, `nome`, `cnpj`, `modo_acesso`,
  `certificado`, `observacoes`), validada com Pydantic; todos os erros são listados de uma
  vez com linha e coluna. Cabeçalhos e valores aceitam acentos/maiúsculas
  (`Procuração`, `NÃO`). Nomes e CNPJs repetidos são erro. A lista real fica fora do git
  (dados de clientes); o exemplo é versionado.

## ADR-006 — Seletores só a partir do recon

- **Decisão:** `selectors.py` contém apenas seletores confirmados ou textos visíveis
  descritos na rotina (marcados `PROVISÓRIO`). O restante é `None` com
  `TODO: capturar via recon`. Consulta, parsing e exportação ficam como esqueletos
  (`NotImplementedError`) até termos o HTML real.
