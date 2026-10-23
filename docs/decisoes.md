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
- **Origens:** `CONDOSYS_ISSNET_CERT_ORIGINS`. Padrão `https://api.ihub.com.br` — ver
  ADR-007: quem pede o certificado é o popup do iHub, não o ISSNet.
- **Testado localmente** (`tests/test_browser.py`): servidor HTTPS que exige certificado
  cliente (CA de teste) aceita o `.pfx` moderno e o legado 3DES, com e sem recodificação;
  sem certificado o navegador recebe `ERR_`. Quando o handshake falha, o Playwright **não
  lança exceção**: serve uma página HTTP 503 com o texto `Playwright client-certificate
  error: ...` — o login verifica esse texto (na página e no popup).

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

## ADR-007 — O login do ISSNet DF passa por um popup do iHub (Fase 1)

- **Contexto (verificado em 22/10/2026 na página pública de login, sem certificado):**
  - O botão "Logar com certificado digital" é `<a id="btnAcionaCertificado"
    onclick="btnAssinar_onClick()">`.
  - `btnAssinar_onClick()` chama `ihubauth(<valor de #licencaCertificado>, callback)`
    (script `ihubauth.js` v2, servido por `www.notacontrol.com.br`). Ele abre um popup em
    `https://api.ihub.com.br/auth?token=<licença>`; esse servidor (NGINX com
    `ssl_verify_client optional`) pede o certificado ICP-Brasil **no handshake TLS
    inicial** e devolve um ticket por `postMessage`. A página grava o ticket em
    `#ticketcertificado` e faz `__doPostBack('btnToken')`.
  - `openssl s_client -connect api.ihub.com.br:443` lista 180 ACs ICP-Brasil aceitas,
    incluindo **AC SEMPRE RFB v2** (emissora do certificado do The Sun).
  - Erros do iHub chegam como `alert()` na página de login (códigos 401/402/403/429/456/457;
    457 = "Certificado digital inválido ou não apresentado").
  - A página também carrega `lacuna-web-pki-2.5.0.js`, mas o fluxo atual do botão não o usa.
- **Decisão:** manter o Plano A (`client_certificates`), apontando a origem para
  `https://api.ihub.com.br`. O login clica no botão, acompanha o popup e espera a
  entrada no portal, falhando rápido se o popup mostrar erro de TLS ou se surgir um alerta.
- **Restrição — Cloudflare:** os scripts de `www.notacontrol.com.br` (inclusive
  `ihubauth.js`) são bloqueados para o navegador em **modo invisível** (headless):
  `net::ERR_BLOCKED_BY_RESPONSE.NotSameOrigin` (desafio do Cloudflare). Com a janela
  visível eles carregam normalmente. Por isso `CONDOSYS_HEADLESS=false` é obrigatório; o
  login detecta a ausência de `window.ihubauth` e explica o problema.
- **Custo:** o comentário do `ihubauth.js` diz que cada autenticação "debita saldo" da
  licença do portal no iHub. Evitar logins desnecessários; na coleta em lote (Fase 4),
  agrupar condomínios por certificado e trocar de contribuinte na mesma sessão.
- **Verificação humana (confirmado em 23/10/2026, primeiro login real com o certificado
  da Sema):** com a origem certa, o certificado chega ao iHub e o popup carrega
  "IHub — Autenticação com Certificado Digital", mas pode exibir o Cloudflare Turnstile
  ("Confirme que é humano"); a própria página avisa "Se aparecer uma caixa de verificação
  abaixo, marque-a". **Decisão:** não contornar a proteção. O login fica semiautomático:
  o condosys detecta o iframe `challenges.cloudflare.com` no popup, avisa no terminal e
  estende a espera por `CONDOSYS_HUMAN_CHECK_TIMEOUT_MS` (padrão 180 s) para a pessoa
  marcar a caixa. Consequência para a Fase 4/8: a coleta em lote não roda sem ninguém na
  frente do computador; agrupar por certificado reduz o número de verificações.
- **Erro do primeiro teste real:** `.env` gerado antes desta descoberta mandava o
  certificado para `https://iss.fazenda.df.gov.br` → iHub 457 ("Certificado digital
  inválido ou não apresentado"). A mensagem de erro agora aponta a origem certa.
- **Pendente (teste manual com certificado real):** confirmar o handshake com um A1 real,
  a URL após o login e o seletor de contribuinte (procuração).

## ADR-009 — Login assistido (procuração) e ADN (acesso direto)

- **Contexto (23/10/2026, testes reais com o certificado da Sema):**
  - com a origem certa, o `client_certificates` entrega o certificado ao iHub, mas o popup
    mostra o Cloudflare Turnstile e a verificação **falha mesmo quando uma pessoa marca a
    caixa** ("A verificação de segurança falhou") — o Cloudflare rejeita o navegador
    controlado por automação;
  - o mesmo login feito à mão no Firefox comum, com o certificado instalado no navegador,
    funciona e cai em `online/default/empresas.aspx` (seleção da empresa na procuração).
- **Decisão:** não contornar a proteção (sem "stealth", sem esconder automação).
  1. **Procuração → login assistido** (`CONDOSYS_LOGIN_MODE=assisted`, padrão): o
     condosys abre o Chrome/Edge instalado como um processo comum (perfil próprio em
     `browser-profile/`, porta DevTools local), a pessoa faz o login como hoje (escolhe o
     certificado instalado no sistema, marca a caixa se aparecer) e o condosys **só se
     conecta depois** que uma aba está dentro do portal (sondagem de `/json/list`, que não
     se anexa às páginas). A partir daí ele conduz o portal (seleção da empresa, consulta,
     recon). Um login por certificado.
  2. **Direto → API oficial do ADN** (`GET /contribuintes/DFe/{NSU}?lote=true`, mTLS).
     O manual exige certificado com a **mesma raiz de CNPJ** do consultado, então serve
     para condomínios com certificado próprio, não para procuração. O DF compartilha as
     notas do ISSNet com o ADN. `condosys adn-test` faz uma consulta e salva a resposta
     bruta para confirmar o layout (Fase 3).
     **Confirmado em 23/10/2026** (`adn-test --cert sema.pfx`): HTTP 200, lote de 50 NFS-e
     do DF (município 5300108) em que a Sema é tomadora, com retenções federais, ISSQN e
     valor líquido no XML nacional — detalhes e mapeamento de campos em
     [adn.md](adn.md).
  3. O modo automático (`client_certificates`) continua no código e nos testes, para o caso
     de a proteção mudar.
- **Certificados no navegador:** `condosys cert install <nome>` instala no cofre usado pelo
  Chrome/Edge (Windows: Usuário Atual → Pessoal via `Import-PfxCertificate`; Linux: NSS
  `~/.pki/nssdb` via `pk12util`), com o `.pfx` recodificado e senha descartável — a senha
  real não aparece em linha de comando. O Firefox usa outro cofre e não serve para o modo
  assistido (o Playwright só se conecta a Chrome/Edge).
- **Consequência:** a coleta não roda sem uma pessoa para o login de cada certificado; a
  Fase 4 deve agrupar condomínios por certificado.

## ADR-010 — iHub bloqueia acesso automatizado: automação do portal suspensa

- **Contexto (23/10/2026, 00:56):** no login assistido (Chrome comum aberto pelo
  condosys, login feito pela pessoa), o popup do iHub respondeu: *"Acesso automatizado
  deve usar o webservice do sistema. Se o uso é legítimo, informe ao suporte o código a
  seguir. Ref.: 568F9D19"*. Antes disso, o Cloudflare já reprovava o navegador do
  Playwright (ADR-009). O operador declarou a política: automação deve usar o webservice.
- **Decisão:** respeitar o bloqueio. Nenhuma técnica para esconder a automação ou
  contornar a verificação. `login-test` e `recon` ficam desativados por padrão
  (`CONDOSYS_ISSNET_AUTOMATION_AUTHORIZED=false`) e explicam o motivo. O código do
  portal (seleção da empresa, consulta) fica guardado para o caso de o suporte autorizar.
- **Caminhos legítimos:**
  1. **ADN (API oficial)** para condomínios com certificado próprio — já funciona
     (docs/adn.md).
  2. **Suporte do ISSNet/NotaControl**, citando a Ref. 568F9D19: perguntar qual
     webservice serve para consultar notas **tomadas** por um procurador (certificado da
     contabilidade) e se o uso pretendido pode ser autorizado.
  3. **Certificados dos condomínios** (ou outro mecanismo que o ADN aceite) para levar os
     condomínios de procuração ao ADN.
  4. Enquanto isso, a consulta no portal continua manual (navegador comum, sem condosys).
- **Consequência:** a Fase 2 (consulta pelo portal) fica bloqueada até haver resposta do
  suporte; a prioridade passa a ser o ADN (paginação, parsing do XML nacional, Excel).

## ADR-008 — Gravação do recon

- **Decisão:** `PageRecorder` salva HTML (página + frames) e screenshot a cada evento
  `load`, registra as requisições (sem cabeçalhos, cookies ou corpos) e salva downloads.
  Um botão "Capturar" é injetado (shadow DOM, removido do HTML salvo) para telas que mudam
  por postback parcial do ASP.NET, que não dispara `load`.
- **Achado:** na API síncrona do Playwright, chamar a API (ex.: `page.content()`) dentro do
  callback de `expose_binding` **trava**; dentro de handlers de `load` funciona. Por isso
  o botão envia o próprio HTML pelo binding e o screenshot é tirado depois (`flush()`).
- **Trace opcional** (`--trace`): `trace.zip` do Playwright tem DOM e rede de cada ação,
  mas inclui cookies — fica em `debug/` (fora do git) e só é gerado quando pedido.
