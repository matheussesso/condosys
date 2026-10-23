# Prompt inicial — condosys

> Como usar: abra a pasta `condosys` no VS Code, inicie o Claude Code, ative o **plan mode** (Shift+Tab) e envie:
> `Leia o arquivo PROMPT_INICIAL.md e execute as instruções dele.`
> Antes, copie o PDF `Rotinas_Fiscal_Ok.pdf` para `docs/rotina-fiscal.pdf`.

---

## 1. Contexto

Você vai criar do zero o **condosys**, um sistema em Python que automatiza a rotina do departamento fiscal de um escritório de contabilidade especializado em condomínios, no Distrito Federal.

Hoje, todo mês (ex.: em outubro, trabalha-se a competência de setembro), um funcionário faz manualmente, para cada condomínio:

1. Abre o portal **ISSNet On-Line — Nota Eletrônica** da Secretaria de Fazenda do DF: `https://iss.fazenda.df.gov.br/online/Login/Login.aspx?ReturnUrl=%2fonline`
2. Clica em **"Logar com certificado digital"** e escolhe o certificado correto. Existem dois modos de acesso:
   - **Direto:** certificado do próprio condomínio (ex.: "THE SUN FULL CONDOMINIUM RESORT", CNPJ 12166128000109).
   - **Por procuração:** certificado da contabilidade (**i9 Brasil** ou **Sema Contabilidade**). Após o login, o portal lista os condomínios autorizados e é preciso selecionar o desejado (há um seletor de contribuinte no cabeçalho, ao lado da competência).
3. Vai em **Menu → Declaração de Serviços Contratados → Consulta de Notas Tomadas**.
4. Preenche os filtros: Série = "Nota Fiscal de Serviço Eletrônica - NFS-e"; expande "Filtros Adicionais" (botão ▽); Data Emissão Inicial/Final = primeiro e último dia da competência; Status NFS-e = "Normal". Clica em **Localizar**.
5. A grade "Documentos Fiscais" mostra: Nº Doc., Valor Nota, Valor Total ISSQN, Data Emissão, Imposto Retido, CPF/CNPJ, Razão Social Prestador, Status, Versão, e botões por linha (Visualizar, um ícone de documento — possivelmente XML/PDF —, Imprimir).
6. Abre cada nota ("Visualizar") para conferir código de serviço (LC 116), descrição, local da prestação, ISSQN, PIS/COFINS/CSLL ("Contribuições Sociais — Retidas", conforme a NT 07 da NFS-e), INSS, IRRF e valor líquido.
7. Lança os dados em planilhas de controle (hoje no Google Sheets: "Controle de PIS", "Controle de INSS" e controle de ISSQN).

O detalhamento completo está em `docs/rotina-fiscal.pdf` — leia-o antes de planejar.

**Todos os certificados são A1 (.pfx).** Os computadores dos funcionários usam **Windows**; eu desenvolvo em **Linux (Debian)**. O sistema precisa rodar nos dois.

## 2. Objetivo desta primeira sessão

O projeto será construído **de forma incremental**. Nesta sessão, entregue apenas:

- **Fase 0 — Fundação:** estrutura do projeto, ferramentas, convenções, documentação e roadmap.
- **Fase 1 — Login e reconhecimento:** conseguir autenticar no ISSNet com um `.pfx` e ter uma ferramenta de reconhecimento para capturar o HTML real das telas.

**Não implemente** a consulta, o parsing das notas nem a exportação completa ainda: os seletores dependem do HTML real, que vamos capturar na Fase 1. Deixe esses módulos como esqueletos com `TODO` e `NotImplementedError`.

## 3. Decisões técnicas (obrigatórias)

- **Python 3.12+**, gerenciado com **uv** (`pyproject.toml`, `uv.lock`), layout `src/`.
- **Playwright (sync API)** para o navegador. A autenticação por certificado deve usar o recurso nativo `client_certificates` do `browser.new_context(...)`, passando `origin`, `pfxPath` e `passphrase`. **Confirme na documentação oficial do Playwright para Python** os nomes exatos das chaves e a versão mínima. Um contexto novo por certificado — isso elimina o problema atual de "trocar certificado / fechar sessão".
- **Typer** para CLI, **Rich** para saída no terminal.
- **Pydantic v2** para modelos e validação de configuração; **pydantic-settings** para configurações gerais.
- **openpyxl** para Excel.
- **keyring** para guardar as senhas dos `.pfx` (Gerenciador de Credenciais no Windows, Secret Service no Linux). **Nunca** gravar senha em arquivo, código ou log.
- **pytest** para testes; **ruff** (lint + format) e **mypy** (strict no pacote).
- **Logging** com o módulo `logging` padrão: console (Rich) + arquivo rotativo em `logs/`.
- Empacotamento futuro com **PyInstaller** (apenas deixe previsto no roadmap).

### Plano B para a autenticação

Se o `client_certificates` do Playwright falhar com o ISSNet (ex.: o IIS pedir o certificado via renegociação TLS só na rota de login), **não force soluções frágeis**. Documente o erro exato em `docs/decisoes.md` e proponha as alternativas, nesta ordem:
1. Ajustar a `origin`/rota do certificado ou usar `channel="msedge"`/`"chrome"`.
2. Fazer o login por HTTP puro (`httpx` ou `requests` + `requests-pkcs12`) e reaproveitar os cookies no Playwright.
3. Chromium com política `AutoSelectCertificateForUrls` e certificado instalado no repositório do sistema (somente Windows).

## 4. Convenções de código

- Identificadores (variáveis, funções, classes, arquivos) em **inglês**.
- Comentários inline em **inglês**.
- Documentação (`README.md`, `docs/`, `CLAUDE.md`, `ROADMAP.md`) em **português**.
- Docstrings em inglês, estilo Google.
- Type hints em tudo.
- **Separar navegação de parsing**: classes de página (Page Object) só navegam e devolvem HTML/dados brutos; funções de parsing são puras, recebem HTML/XML e devolvem modelos Pydantic — e são testadas com fixtures HTML salvas em `tests/fixtures/`.
- Seletores ficam centralizados em um único módulo por portal (`selectors.py`), nunca espalhados.
- **Nunca invente seletores.** Quando não souber, deixe `TODO: capturar via recon` e explique como obter.
- Valores monetários sempre como `Decimal`, nunca `float`. Datas como `date`.
- CNPJ sempre normalizado (só dígitos) internamente, formatado só na saída.

## 5. Estrutura esperada

```
condosys/
├── CLAUDE.md                  # contexto e regras do projeto para o Claude Code
├── README.md                  # como instalar, configurar e usar (pt-BR)
├── ROADMAP.md                 # fases e checklist
├── pyproject.toml
├── .gitignore                 # incluir: certs/, *.pfx, *.p12, output/, logs/, debug/, .env, .venv/
├── .env.example
├── config/
│   └── condominios.example.xlsx   # modelo da lista de condomínios (gerado por comando)
├── certs/                     # .pfx locais (ignorado pelo git) + .gitkeep
├── docs/
│   ├── rotina-fiscal.pdf
│   ├── arquitetura.md
│   ├── decisoes.md            # registro de decisões técnicas (ADR simples)
│   └── issnet-mapa.md         # mapa das telas/seletores do ISSNet (preenchido após o recon)
├── src/condosys/
│   ├── __init__.py
│   ├── __main__.py
│   ├── cli.py                 # comandos Typer
│   ├── settings.py            # pydantic-settings (caminhos, headless, timeouts)
│   ├── logging_setup.py
│   ├── models.py              # Condominium, Certificate, Invoice, InvoiceDetail, RunResult
│   ├── config_loader.py       # lê e valida config/condominios.xlsx
│   ├── credentials.py         # keyring: salvar/ler/remover senha de .pfx
│   ├── certificates.py        # ler .pfx: titular, CNPJ, emissor, validade (cryptography)
│   ├── browser.py             # fábrica de browser/context com client_certificates
│   ├── portals/
│   │   └── issnet/
│   │       ├── __init__.py
│   │       ├── selectors.py
│   │       ├── session.py     # login, seleção do condomínio (procuração), logout
│   │       ├── invoices_page.py   # esqueleto: navegar até Consulta de Notas Tomadas e filtrar
│   │       └── parsers.py     # esqueleto: parse da grade e da nota
│   ├── exporters/
│   │   └── excel.py           # esqueleto da exportação
│   └── services/
│       └── collect.py         # orquestra: para cada condomínio → login → consulta → exporta
└── tests/
    ├── conftest.py
    ├── fixtures/
    ├── test_models.py
    ├── test_config_loader.py
    └── test_certificates.py
```

## 6. Configuração dos condomínios

O arquivo `config/condominios.xlsx` substitui a "lista de referência" que o setor usa hoje para saber qual certificado usar. Colunas:

| coluna | descrição |
|---|---|
| `ativo` | SIM/NÃO |
| `nome` | nome do condomínio |
| `cnpj` | CNPJ do condomínio |
| `modo_acesso` | `DIRETO` ou `PROCURACAO` |
| `certificado` | nome do arquivo `.pfx` em `certs/` (ex.: `the-sun.pfx`, `i9-brasil.pfx`, `sema.pfx`) |
| `observacoes` | texto livre (ex.: "LED: ISSQN zerado, registrar mesmo assim") |

Validar com Pydantic: CNPJ válido (dígitos verificadores), certificado existente, modo de acesso válido. Erros devem ser mostrados de forma clara, indicando a linha da planilha.

## 7. Comandos da CLI (Fases 0 e 1)

- `condosys init` — cria pastas, gera `config/condominios.example.xlsx` e `.env` a partir do exemplo.
- `condosys cert add <arquivo.pfx>` — pede a senha (oculta), valida abrindo o `.pfx`, salva no keyring e mostra titular, CNPJ, emissor e validade.
- `condosys cert list` — lista os certificados em `certs/` com titular, CNPJ, validade, **dias para vencer** (destacar em amarelo < 30 dias, vermelho se vencido) e se a senha está no keyring.
- `condosys cert remove <nome>` — remove a senha do keyring.
- `condosys config check` — valida `condominios.xlsx` e cruza com os certificados (o CNPJ do certificado bate com o condomínio no modo DIRETO?).
- `condosys login-test <nome-do-condominio>` — abre o navegador (visível por padrão), faz login com o certificado correto, seleciona o condomínio se for procuração, confirma que entrou no ambiente certo (lendo o nome/CNPJ exibido no cabeçalho) e tira um screenshot em `debug/`.
- `condosys recon <nome-do-condominio>` — faz o login e chama `page.pause()` para abrir o **Playwright Inspector**, permitindo que eu navegue manualmente e grave seletores. Além disso, registra um listener que salva automaticamente HTML + screenshot de cada página carregada em `debug/recon/<timestamp>/`. Esse material será usado para escrever `selectors.py`, `docs/issnet-mapa.md` e as fixtures de teste da Fase 2.

## 8. Modelos (definir já, mesmo que a coleta venha depois)

- `Invoice` (linha da grade): `number`, `issue_date`, `amount`, `iss_amount`, `tax_withheld: bool`, `provider_document`, `provider_name`, `status`, `version`.
- `InvoiceDetail` (nota aberta): tudo do `Invoice` + `service_code`, `service_description`, `service_location`, `pis`, `cofins`, `csll`, `social_contributions_withheld`, `inss`, `irrf`, `iss_withheld`, `deductions`, `net_amount`, `taker_document`, `taker_name`, `raw_source` (`"html"` ou `"xml"`).
- `Flag` (alertas da pré-análise, para fases futuras): `code`, `severity`, `message`.

## 9. Segurança

- `.pfx` só em `certs/`, ignorado pelo git. Senhas só no keyring.
- Nunca logar senhas, conteúdo de certificados nem cookies de sessão.
- Screenshots e HTML em `debug/` podem conter dados fiscais: pasta ignorada pelo git e mencionada no README.
- Respeitar o portal: um condomínio por vez, pausas curtas entre ações, timeouts configuráveis, sem paralelismo agressivo.

## 10. Roadmap (escrever em `ROADMAP.md`)

- **Fase 0 — Fundação** ✅ (esta sessão)
- **Fase 1 — Login e recon** ✅ (esta sessão)
- **Fase 2 — Consulta de notas:** navegar até Consulta de Notas Tomadas, filtrar pela competência, ler a grade (com paginação), testes com fixtures do recon.
- **Fase 3 — Detalhe das notas:** abrir cada nota; verificar se o ícone ao lado de "Visualizar" baixa o **XML** — se sim, preferir XML a HTML. Investigar também se as notas do DF estão disponíveis na **API do Ambiente de Dados Nacional (ADN) da NFS-e** via certificado, o que dispensaria o navegador.
- **Fase 4 — Exportação Excel:** aba "Notas" (uma linha por nota, todos os campos), aba "Resumo" (por condomínio: qtd. de notas, totais) e aba "Erros" (condomínios que falharam e o motivo). Nome: `output/notas_<competencia>_<data-hora>.xlsx`. Comando `condosys collect --competencia 09/2026 [--condominio X]`.
- **Fase 5 — Enriquecimento por CNPJ:** consultar API pública (ex.: BrasilAPI) para Simples Nacional, MEI e CNAE do prestador, com cache local (SQLite).
- **Fase 6 — Pré-análise de retenções:** regras configuráveis por código de serviço (LC 116) mantidas pela equipe; gerar alertas (ex.: "IRRF destacado — condomínio não retém IRRF", "possível retenção de INSS 11%", "PIS/COFINS não somados à CSLL — verificar NT 07", "nota de venda com indício de serviço"). **O sistema sinaliza; o funcionário decide.** Calcular sugestão de 4,65% e de base de INSS (retido ÷ 0,11) apenas como referência.
- **Fase 7 — Conferência com as planilhas de controle:** ler as planilhas do Google Sheets e marcar cada nota como "nova" ou "já lançada".
- **Fase 8 — Interface simples para o funcionário:** janela mínima (escolher competência, condomínios, botão Executar, barra de progresso, abrir Excel ao final) e executável Windows via PyInstaller.
- **Fase 9 (futuro) — e-CAC / DARF:** avaliar viabilidade (gov.br + captcha); provavelmente semi-automatizado.

## 11. CLAUDE.md

Crie um `CLAUDE.md` conciso para orientar as próximas sessões, contendo: resumo do projeto, comandos (`uv run ...`, testes, lint), arquitetura em poucas linhas, convenções da seção 4, regras de segurança da seção 9, a regra "nunca inventar seletores — usar os dados de `debug/recon` e `docs/issnet-mapa.md`", e a instrução de sempre atualizar `ROADMAP.md` e `docs/decisoes.md` ao concluir uma fase.

## 12. Forma de trabalho

1. Leia `docs/rotina-fiscal.pdf` e este arquivo inteiro.
2. Apresente o plano (plan mode) e aguarde minha aprovação.
3. Implemente a Fase 0, rode `ruff`, `mypy` e `pytest` e corrija até passar.
4. Implemente a Fase 1. Os comandos que dependem do portal real eu testarei manualmente — me diga exatamente o que rodar, na ordem (incluindo `playwright install chromium`).
5. Faça `git init` e um commit por fase com mensagens claras em português.
6. Ao final, me entregue: o que foi feito, o que ficou pendente e os passos para eu executar o recon e trazer os resultados para a Fase 2.
