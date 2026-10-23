# Guia de testes do condosys

Como instalar, testar e validar o condosys no **Linux** e no **Windows**, do zero até o
recon no portal real. Vale para as Fases 0 e 1 (fundação, login e recon). Ao concluir
novas fases, este guia deve ganhar as seções correspondentes.

Sumário:

1. [Visão geral](#1-visão-geral)
2. [Instalação](#2-instalação)
3. [Testes automatizados](#3-testes-automatizados)
4. [Roteiro de teste manual](#4-roteiro-de-teste-manual)
5. [Recon no portal real](#5-recon-no-portal-real)
6. [Erros comuns e o que fazer](#6-erros-comuns-e-o-que-fazer)
7. [Diferenças entre Windows e Linux](#7-diferenças-entre-windows-e-linux)
8. [Logs e depuração](#8-logs-e-depuração)
9. [Cuidados durante os testes](#9-cuidados-durante-os-testes)
10. [Checklist de aceite das Fases 0 e 1](#10-checklist-de-aceite-das-fases-0-e-1)

---

## 1. Visão geral

Há dois tipos de teste:

| tipo | o que cobre | precisa de certificado real? | acessa o portal? |
|---|---|---|---|
| **Automatizados** (`pytest`) | CNPJ, modelos, planilha, leitura de `.pfx`, cofre de senhas, CLI, login completo contra um portal falso local, gravador do recon | não (gera certificados de teste) | não |
| **Manuais** | cadastro dos certificados reais, planilha real, login no ISSNet, recon | sim | sim |

Os testes automatizados **nunca** tocam o cofre de senhas real nem o portal. O login
real, a seleção do contribuinte na procuração e as telas internas do ISSNet só podem ser
validados manualmente.

Como funciona o login (resumo, detalhes no ADR-007 de [decisoes.md](decisoes.md)): o
botão "Logar com certificado digital" abre um popup em `https://api.ihub.com.br/auth`;
esse servidor pede o certificado na conexão TLS, o condosys entrega o `.pfx` ao
navegador sem janela de escolha, o popup devolve um ticket e a página entra no portal.

---

## 2. Instalação

### 2.1 Linux (Debian)

```bash
# 1. uv (gerenciador de Python) — uma vez por máquina
curl -LsSf https://astral.sh/uv/install.sh | sh

# 2. Projeto
cd ~/Documents/Workspace/Pessoal/condosys     # ou onde o repositório estiver
uv sync                                        # cria .venv e instala dependências (baixa o Python 3.12)
uv run playwright install chromium             # baixa o Chromium do Playwright
uv run condosys init                           # pastas, .env e planilha de exemplo
```

Se o Chromium não abrir por falta de bibliotecas do sistema:

```bash
uv run playwright install-deps chromium        # usa sudo/apt
```

Cofre de senhas: o GNOME Keyring ou o KWallet precisa estar instalado e **desbloqueado**
(normalmente ele desbloqueia ao entrar na sessão gráfica). Para conferir:

```bash
uv run python -c "import keyring; print(keyring.get_keyring())"
# esperado: keyring.backends.SecretService.Keyring
```

### 2.2 Windows

No PowerShell:

```powershell
# 1. uv — uma vez por máquina
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
# feche e abra o PowerShell para o comando "uv" aparecer

# 2. Git (se não tiver): https://git-scm.com/download/win

# 3. Projeto
git clone <url-do-repositorio> condosys
cd condosys
uv sync
uv run playwright install chromium
uv run condosys init
```

Alternativa ao Chromium baixado: usar o **Microsoft Edge** já instalado. No `.env`:

```
CONDOSYS_BROWSER_CHANNEL=msedge
```

O cofre de senhas no Windows é o **Gerenciador de Credenciais** (Painel de Controle →
Gerenciador de Credenciais → Credenciais do Windows; as entradas aparecem como
`condosys`). Não é preciso configurar nada.

### 2.3 Conferir a instalação

```bash
uv run condosys --version        # condosys 0.1.0
uv run condosys --help           # lista de comandos
```

Os comandos podem ser rodados de qualquer subpasta do projeto (por exemplo, de dentro de
`certs/`): o condosys procura a pasta do projeto subindo a partir da pasta atual.

---

## 3. Testes automatizados

### 3.1 Rodar

```bash
uv run pytest                       # tudo (69 testes, ~10 s)
uv run pytest -m "not browser"      # sem os testes de navegador (não precisa de Chromium)
uv run pytest -m browser            # só os de navegador
uv run pytest tests/test_models.py  # um arquivo
uv run pytest -k cnpj -v            # por nome, mostrando cada teste
```

Qualidade de código (devem passar antes de qualquer commit):

```bash
uv run ruff check .                 # lint
uv run ruff format --check .        # formatação (sem --check para corrigir)
uv run mypy                         # tipos, modo strict
```

Tudo de uma vez:

```bash
uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run pytest
```

Resultado esperado: `All checks passed!`, `Success: no issues found` e `69 passed`.
Os testes de navegador são **pulados** (não falham) se o Chromium não estiver instalado.

### 3.2 O que cada arquivo testa

| arquivo | testes | cobre |
|---|---|---|
| `tests/test_models.py` | 36 | CNPJ numérico e alfanumérico (dígitos verificadores, formatação, zeros à esquerda vindos do Excel), valores em reais (`"R$ 1.234,56"` → `Decimal`, recusa `float`), competência (`09/2026`, fevereiro bissexto), validação do condomínio, nome do arquivo de saída sem `:` |
| `tests/test_config_loader.py` | 7 | planilha de exemplo válida, acentos e variações (`Procuração`, `NÃO`, `Observações`), erros com linha e coluna, linhas em branco, nomes/CNPJs repetidos, colunas ausentes, busca de condomínio por nome/CNPJ |
| `tests/test_certificates.py` | 9 | leitura do titular/CNPJ (campo ICP-Brasil e nome "EMPRESA:CNPJ"), certificado sem CNPJ, vencido, senha errada, arquivo ausente, `.pfx` legado (3DES) recodificado, listagem de `certs/`, cofre de senhas |
| `tests/test_cli.py` | 8 | `init`, `cert add/list/remove`, senha errada, `config check` (OK e certificado DIRETO de outro CNPJ), planilha inválida, `login-test` sem senha, comandos rodados de subpasta |
| `tests/test_browser.py` | 9 | ver 3.3 |

### 3.3 Como funcionam os testes de navegador

`tests/test_browser.py` sobe servidores locais e não acessa a internet:

- **Servidor HTTPS com certificado cliente obrigatório** (imita o `api.ihub.com.br`):
  uma AC de teste assina o certificado do "THE SUN"; o servidor só aceita esse
  certificado. Verifica `.pfx` moderno e legado, com e sem recodificação, e que sem
  certificado a conexão é recusada.
- **Portal ISSNet falso**: página de login com `#btnAcionaCertificado` e `ihubauth()`, que
  abre o popup no servidor acima e recebe o ticket por `postMessage`, como no portal real.
  Testa:
  - login completo e conferência do CNPJ na página;
  - certificado de outra AC → erro "handshake TLS" em menos de 6 s;
  - scripts de login ausentes (o que o Cloudflare causa em modo invisível) → erro
    explicando o Cloudflare.
- **Gravador do recon**: navega entre páginas com iframe, clica no botão "Capturar" e
  confere HTML, frames, screenshots, `index.jsonl` e `requests.log`.

### 3.4 Cofre de senhas nos testes

`tests/conftest.py` troca o keyring por um cofre em memória em **todos** os testes
(fixture `memory_keyring`, automática). Nenhum teste lê ou grava no Gerenciador de
Credenciais / Secret Service reais.

---

## 4. Roteiro de teste manual

Siga na ordem. Cada passo diz o resultado esperado. Use `-v` em qualquer comando para ver
mensagens detalhadas (ex.: `uv run condosys -v config check`).

### 4.1 Inicialização

```bash
uv run condosys init
```

Esperado: pastas `certs/`, `config/`, `output/`, `logs/`, `debug/`; arquivo `.env`;
`config/condominios.example.xlsx`. Rodar de novo não apaga nada (o `.env` existente é
mantido).

### 4.2 Certificados

Cadastre cada certificado com um nome curto e sem espaços:

```bash
# Linux
uv run condosys cert add "/caminho/THE SUN.pfx" --name the-sun.pfx
uv run condosys cert add "/caminho/SEMA.pfx"    --name sema.pfx
uv run condosys cert add "/caminho/I9.pfx"      --name i9-brasil.pfx
```

```powershell
# Windows
uv run condosys cert add "C:\Users\fulano\Downloads\THE SUN.pfx" --name the-sun.pfx
```

Esperado: pede a senha sem mostrá-la, copia o arquivo para `certs/` (se ainda não estiver
lá) e mostra titular, CNPJ, emissor e validade.

**Confira se o titular é o esperado** antes de seguir. Um `.pfx` cadastrado com o nome
errado (ex.: o da Sema como `the-sun.pfx`) faz o login entrar no ambiente errado; o
`config check` acusa isso no modo DIRETO.

Casos para testar:

| ação | esperado |
|---|---|
| `cert add` com senha errada | `Erro: ... senha incorreta ou arquivo inválido`, nada é copiado |
| `cert add` de um arquivo com nome já existente em `certs/` | erro pedindo `--overwrite` ou `--name` |
| `cert list` | tabela com dias para vencer: verde, **amarelo** (< 30 dias), **vermelho** (vencido) |
| `cert remove the-sun.pfx` e depois `cert list` | senha "não cadastrada" (o arquivo continua em `certs/`) |

Para apagar de vez um certificado: `cert remove <nome>` e depois apague o arquivo em `certs/`.

### 4.3 Planilha de condomínios

```bash
cp config/condominios.example.xlsx config/condominios.xlsx     # Linux
copy config\condominios.example.xlsx config\condominios.xlsx   # Windows
```

Edite `config/condominios.xlsx` (aba `condominios`):

| ativo | nome | cnpj | modo_acesso | certificado | observacoes |
|---|---|---|---|---|---|
| SIM | THE SUN FULL CONDOMINIUM RESORT | 12.166.128/0001-09 | DIRETO | the-sun.pfx | |
| SIM | (condomínio da Sema) | (CNPJ do condomínio) | PROCURACAO | sema.pfx | |

No modo `PROCURACAO`, o CNPJ é o **do condomínio**, e o certificado é o da contabilidade.
Apague as linhas de exemplo que não existirem.

```bash
uv run condosys config check
```

Esperado: tabela com uma linha por condomínio e status `OK`, `ALERTA` (ex.: certificado
vence em menos de 30 dias) ou `ERRO`. Termina com "Configuração válida." ou com código de
saída 1 se algum condomínio **ativo** tiver erro.

Erros para provocar de propósito (e conferir a mensagem com linha e coluna):

| altere | mensagem esperada |
|---|---|
| um dígito do CNPJ | `linha N, coluna 'cnpj': CNPJ inválido` |
| `modo_acesso` = `OUTRO` | `linha N, coluna 'modo_acesso': use DIRETO ou PROCURACAO` |
| `certificado` = `nao-existe.pfx` | `linha N, coluna 'certificado': certificado não encontrado` |
| `ativo` = `TALVEZ` | `linha N, coluna 'ativo': use SIM ou NÃO` |
| dois condomínios com o mesmo nome | `nome repetido (já usado na linha N)` |
| DIRETO com o certificado de outra empresa | `modo DIRETO, mas o certificado é de <CNPJ> (<titular>)` |

Desfaça as alterações depois.

### 4.4 Login — acesso DIRETO

Cada login consome saldo da licença do portal no iHub; não repita sem necessidade.

```bash
uv run condosys login-test "the sun"
```

O que acontece:

1. Abre o navegador (janela visível) na página de login do ISSNet.
2. Clica em "Logar com certificado digital".
3. Abre o popup do iHub e fecha sozinho, **sem pedir para escolher certificado**.
4. Entra no portal, procura o CNPJ do condomínio na página e tira um screenshot.

Resultado no terminal:

| campo | significado |
|---|---|
| Página / URL | onde o navegador parou (a URL é mostrada sem parâmetros) |
| CNPJ na página | `sim` = entrou no ambiente do condomínio certo |
| Nome na página | indicação extra; pode ser `não` se o portal abrevia o nome |
| Screenshot | `debug/login-test_<condominio>_<data-hora>.png` |

Códigos de saída: `0` confirmado · `1` erro (mensagem explica) · `2` entrou, mas o CNPJ não
apareceu na página (veja o screenshot; o recon vai mapear o cabeçalho).

Se falhar, o screenshot do erro fica em `debug/login-test_<condominio>_<data-hora>_erro.png`.

### 4.5 Login — acesso por PROCURAÇÃO

```bash
uv run condosys login-test "<nome do condomínio da Sema>"
```

Até o seletor de contribuinte ser mapeado no recon, o passo é manual:

1. O login com o certificado da Sema acontece sozinho.
2. O terminal mostra: `Passo manual: na janela do navegador, selecione o contribuinte ...`.
3. Escolha o condomínio no seletor do cabeçalho do portal (ao lado da competência).
4. Volte ao terminal e pressione **Enter**.
5. O condosys confere o CNPJ do condomínio na página e tira o screenshot.

Anote como o seletor funciona (lista, campo de busca, nova página?), pois isso será
automatizado.

---

## 5. Recon no portal real

O recon grava o HTML real das telas para escrevermos os seletores e os testes da Fase 2.
Faça **um recon com acesso DIRETO e outro com PROCURAÇÃO**.

```bash
uv run condosys recon "the sun"
uv run condosys recon "the sun" --trace    # também grava trace.zip (contém cookies)
```

### 5.1 Como usar

- O login é feito sozinho e o **Playwright Inspector** abre ao lado do navegador.
- **Cada página carregada é salva sozinha** (HTML, frames e screenshot).
- O botão **Capturar** (canto inferior direito da página) salva a tela atual. Use-o
  sempre que a tela mudar **sem recarregar**: depois de "Localizar", ao expandir "Filtros
  Adicionais", ao trocar de página da grade, ao trocar de contribuinte.
- No Inspector, **Pick locator** + passar o mouse num elemento mostra o seletor dele.
- **Resume** (▶) no Inspector solta o navegador para navegar livremente; o botão Capturar e
  a gravação continuam funcionando.
- Para terminar, **feche todas as abas** do navegador. O terminal mostra quantas capturas
  foram feitas.

Se o login falhar, o Inspector abre mesmo assim, para investigar a tela de erro.

### 5.2 Roteiro de telas

Marque cada item ao capturar:

- [ ] Tela inicial após o login (cabeçalho com nome/CNPJ e competência)
- [ ] **Procuração:** seletor de contribuinte aberto, e a tela depois de trocar de condomínio
- [ ] Menu aberto → Declaração de Serviços Contratados
- [ ] Tela "Consulta Notas Tomadas" vazia
- [ ] Campo Série com a opção "Nota Fiscal de Serviço Eletrônica - NFS-e"
- [ ] "Filtros Adicionais" expandido (▽)
- [ ] Datas preenchidas (ex.: 01/09/2026 a 30/09/2026) e Status NFS-e = Normal
- [ ] Grade "Documentos Fiscais" **com resultados** (Capturar)
- [ ] Grade **sem resultados** (ex.: uma competência sem notas) (Capturar)
- [ ] Grade com **mais de uma página**: página 1 e página 2 (Capturar em cada)
- [ ] Nota aberta com "Visualizar" (pode abrir popup ou nova aba)
- [ ] Ícone ao lado de "Visualizar": baixa XML? PDF? (o arquivo vai para `downloads/`)
- [ ] Botão "Imprimir" (o que abre)
- [ ] Botão/link de sair (logout)

### 5.3 O que fica salvo

Pasta `debug/recon/<AAAAMMDD-HHMMSS>/`:

| arquivo | conteúdo |
|---|---|
| `NNN_load_<pagina>.html` / `.png` | página carregada e screenshot da página inteira |
| `NNN_manual_<pagina>.html` / `.png` | capturas pelo botão Capturar |
| `NNN_*.frameK.html` | HTML de cada iframe da página |
| `index.jsonl` | uma linha por captura: hora, tipo, URL, título, arquivos |
| `requests.log` | método, tipo, status e URL de cada requisição (sem cookies ou cabeçalhos) |
| `downloads/` | arquivos baixados (XML/PDF das notas) |
| `trace.zip` | só com `--trace`; abrir com `uv run playwright show-trace debug/recon/<pasta>/trace.zip` |

### 5.4 O que trazer para a Fase 2

1. A saída do terminal do `login-test` (DIRETO e PROCURAÇÃO).
2. O caminho das pastas `debug/recon/<data-hora>/` (não envie para o git).
3. Os seletores anotados no Inspector, se houver.
4. Observações: o "Visualizar" abre popup? O seletor de contribuinte recarrega a página?
   A grade tem quantas linhas por página? O ícone baixa XML?

---

## 6. Erros comuns e o que fazer

| mensagem | causa provável | o que fazer |
|---|---|---|
| `Não foi possível acessar o cofre de senhas do sistema` | Linux sem GNOME Keyring/KWallet ou cofre bloqueado | instale/desbloqueie o cofre (`gnome-keyring`, `seahorse`) e entre de novo na sessão gráfica |
| `senha do certificado X não cadastrada` | o `.pfx` está em `certs/` mas a senha não foi salva neste computador | `uv run condosys cert add certs/X` |
| `senha incorreta ou arquivo inválido` | senha errada ou arquivo corrompido | confira a senha; teste abrindo o `.pfx` no Windows |
| `Planilha inválida: ... arquivo não encontrado` | falta `config/condominios.xlsx` | copie o exemplo (4.3) |
| `nenhum condomínio corresponde a 'X'` / `corresponde a vários` | nome digitado não bate ou é ambíguo | use mais palavras do nome ou o CNPJ |
| `não foi possível abrir o navegador (rode: uv run playwright install chromium)` | Chromium não instalado | rode o comando; no Linux, também `playwright install-deps chromium` |
| `os scripts de login do portal não carregaram (o Cloudflare bloqueia...)` | navegador em modo invisível | `CONDOSYS_HEADLESS=false` no `.env` e não use `--headless` |
| `o handshake TLS com o certificado falhou` | o iHub recusou o certificado (vencido, AC não aceita, `.pfx` errado) | `cert list` para conferir validade/titular; guarde a mensagem completa |
| `alerta do portal: Certificado digital inválido ou não apresentado.` | iHub código 457 | confira se `CONDOSYS_ISSNET_CERT_ORIGINS` contém `https://api.ihub.com.br` |
| `alerta do portal: Certificado digital revogado.` | iHub código 456 | certificado precisa ser substituído |
| `alerta do portal: Token de licença inválido ou saldo zerado.` | iHub código 403 — licença do portal | problema do portal/licença, não do condosys; tente mais tarde |
| `alerta do portal: Muitas requisições...` | iHub código 429 | aguarde alguns minutos |
| `alerta do portal: Licença inválida ou JWT de sessão expirado` / `Domínio não autorizado` | iHub códigos 401/402 | recarregue e tente de novo; se repetir, registre em `docs/decisoes.md` |
| `o login não foi concluído no tempo limite` | portal lento ou mudou | aumente `CONDOSYS_NAVIGATION_TIMEOUT_MS`; rode o recon para ver a tela |
| `o certificado não foi enviado para <origem>` | o portal passou a pedir certificado em outro endereço | inclua a origem em `CONDOSYS_ISSNET_CERT_ORIGINS` no `.env` |
| login-test termina com código 2 | entrou, mas o CNPJ não aparece no texto da página | confira o screenshot; capture o cabeçalho no recon |

Se nada disso resolver, siga o **Plano B** em [decisoes.md](decisoes.md) (ADR-002) e
registre lá o erro exato.

---

## 7. Diferenças entre Windows e Linux

| assunto | Windows | Linux |
|---|---|---|
| terminal | PowerShell (ou Terminal do Windows) | bash |
| caminhos com espaço | `"C:\Users\fulano\Downloads\THE SUN.pfx"` | `"/home/fulano/THE SUN.pfx"` |
| cofre de senhas | Gerenciador de Credenciais (sem configuração) | Secret Service: GNOME Keyring/KWallet desbloqueado |
| navegador | Chromium do Playwright ou Edge (`CONDOSYS_BROWSER_CHANNEL=msedge`) | Chromium do Playwright (`chrome` se o Google Chrome estiver instalado) |
| bibliotecas do navegador | não precisa | às vezes `uv run playwright install-deps chromium` |
| janela do navegador | sempre visível | precisa de sessão gráfica (X11 ou Wayland); não funciona por SSH sem tela |
| senhas cadastradas | por usuário do Windows: cada funcionário cadastra no seu computador | por usuário do Linux |

Em ambos: rode os comandos dentro da pasta do projeto (ou de uma subpasta dela). Nomes de
arquivo gerados nunca têm `:`, para funcionar no Windows.

---

## 8. Logs e depuração

- **Log em arquivo:** `logs/condosys.log` (tudo, inclusive mensagens de depuração; gira a
  cada 2 MB, guarda 5 arquivos).
- **Mais detalhes no terminal:** `uv run condosys -v <comando>`.
- **Screenshots:** `debug/login-test_*.png`.
- **Recon:** `debug/recon/<data-hora>/` (seção 5.3).
- **Trace do Playwright:** `--trace` no recon; mostra cada ação, o DOM e a rede.

Ajustes úteis no `.env` durante testes:

```
CONDOSYS_LOG_LEVEL=DEBUG
CONDOSYS_SLOW_MO_MS=800              # deixa as ações mais lentas para acompanhar
CONDOSYS_NAVIGATION_TIMEOUT_MS=90000 # portal lento
```

---

## 9. Cuidados durante os testes

- **Dados fiscais:** `debug/`, `output/` e `logs/` têm dados dos condomínios. Não envie por
  e-mail/chat nem coloque no git (já estão no `.gitignore`). Ao transformar HTML do recon
  em fixture de teste, prefira anonimizar nomes e CNPJs de terceiros.
- **Certificados e senhas:** `.pfx` só em `certs/` (fora do git); senhas só no cofre. Não
  coloque senha no `.env` nem em mensagens.
- **Saldo do iHub:** cada login consome saldo da licença do portal. Evite rodar
  `login-test` em loop.
- **Respeito ao portal:** um condomínio por vez; não rode vários comandos em paralelo.
- **Validade:** o certificado da Sema vence em **05/11/2026**. Confira sempre com
  `cert list` antes de uma rodada de testes.

---

## 10. Checklist de aceite das Fases 0 e 1

Automatizado (Linux e Windows):

- [ ] `uv sync` sem erros
- [ ] `uv run ruff check .`, `uv run ruff format --check .`, `uv run mypy` sem erros
- [ ] `uv run pytest` → 69 testes passando (nenhum pulado, com o Chromium instalado)

Manual:

- [ ] `condosys init` cria pastas, `.env` e planilha de exemplo
- [ ] `cert add` de cada certificado mostra o titular e o CNPJ corretos
- [ ] `cert list` mostra validade e senha `ok`; cores de vencimento corretas
- [ ] `config check` valida a planilha real; erros provocados aparecem com linha e coluna
- [ ] `login-test` DIRETO: entra sem janela de certificado e confirma o CNPJ (código 0)
- [ ] `login-test` PROCURAÇÃO: entra com o certificado da contabilidade; seleção manual do
      contribuinte funciona e o CNPJ é confirmado
- [ ] `recon` DIRETO e PROCURAÇÃO: roteiro da seção 5.2 capturado
- [ ] Testado no **Linux** e no **Windows**
- [ ] Resultados levados para a Fase 2 (seção 5.4)
