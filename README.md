# condosys

Automação da rotina do departamento fiscal de condomínios (DF): consulta das notas de
serviços tomados no portal **ISSNet On-Line** da Secretaria de Fazenda do DF, usando
certificados digitais A1 (`.pfx`).

> Estado atual: **Fases 0 e 1** (fundação, login e reconhecimento das telas).
> A coleta das notas e a exportação para Excel chegam nas próximas fases — veja o
> [ROADMAP.md](ROADMAP.md).

Roda em **Windows** (computadores do setor) e **Linux** (desenvolvimento).

## Instalação

### 1. Pré-requisitos

- [uv](https://docs.astral.sh/uv/) — gerenciador de Python e dependências.
  - Windows (PowerShell): `powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"`
  - Linux: `curl -LsSf https://astral.sh/uv/install.sh | sh`
- Git.
- Não é preciso instalar Python: o `uv` baixa o Python 3.12 automaticamente.

### 2. Projeto e dependências

```bash
git clone <url-do-repositorio> condosys
cd condosys
uv sync
uv run playwright install chromium
```

No **Linux**, se o Chromium reclamar de bibliotecas ausentes:

```bash
uv run playwright install-deps chromium   # usa sudo/apt
```

No **Windows**, em vez do Chromium baixado, dá para usar o Microsoft Edge já instalado:
coloque `CONDOSYS_BROWSER_CHANNEL=msedge` no `.env`.

Rode os comandos sempre de dentro da pasta do projeto (o `.env` é lido da pasta atual).

### 3. Inicialização

```bash
uv run condosys init
```

Cria as pastas `certs/`, `config/`, `output/`, `logs/`, `debug/`, o arquivo `.env` e a
planilha de exemplo `config/condominios.example.xlsx`.

## Configuração

### Certificados

Cada certificado A1 é cadastrado uma vez por computador:

```bash
uv run condosys cert add "C:\Users\fulano\Downloads\THE SUN.pfx" --name the-sun.pfx
```

O comando pede a senha (não aparece na tela), abre o `.pfx` para validar, copia o arquivo
para `certs/` e guarda a senha no cofre do sistema:

- **Windows:** Gerenciador de Credenciais (Painel de Controle → Gerenciador de Credenciais →
  Credenciais do Windows → `condosys`).
- **Linux:** Secret Service (GNOME Keyring / KWallet). O cofre precisa estar desbloqueado.

```bash
uv run condosys cert list              # titular, CNPJ, validade, dias para vencer, senha ok?
uv run condosys cert remove the-sun.pfx   # apaga só a senha do cofre
```

Na listagem, a validade fica **amarela** com menos de 30 dias e **vermelha** se vencida.

### Lista de condomínios

Copie `config/condominios.example.xlsx` para `config/condominios.xlsx` e preencha:

| coluna | descrição |
|---|---|
| `ativo` | SIM/NÃO |
| `nome` | nome do condomínio |
| `cnpj` | CNPJ do condomínio (com ou sem pontuação) |
| `modo_acesso` | `DIRETO` (certificado do próprio condomínio) ou `PROCURACAO` (i9 Brasil / Sema) |
| `certificado` | nome do arquivo `.pfx` em `certs/` (ex.: `the-sun.pfx`, `i9-brasil.pfx`, `sema.pfx`) |
| `observacoes` | texto livre |

Valide com:

```bash
uv run condosys config check
```

O comando aponta erros por linha/coluna (CNPJ inválido, certificado inexistente, modo de
acesso inválido, nomes repetidos), confere se a senha está no cofre, a validade do
certificado e, no modo `DIRETO`, se o CNPJ do certificado é o do condomínio.

### Ajustes gerais (`.env`)

Veja [.env.example](.env.example): pastas, navegador (`chromium`, `msedge`, `chrome`),
modo invisível, tempos de espera e pausas entre ações. **Nunca** coloque senhas no `.env`.

## Comandos

| comando | o que faz |
|---|---|
| `condosys init` | cria pastas, `.env` e a planilha de exemplo |
| `condosys cert add <arquivo.pfx>` | valida o certificado e guarda a senha no cofre |
| `condosys cert list` | lista certificados, validade e situação da senha |
| `condosys cert remove <nome>` | remove a senha do cofre |
| `condosys cert install <nome>` | instala o certificado no Chrome/Edge (login assistido) |
| `condosys config check` | valida `condominios.xlsx` e cruza com os certificados |
| `condosys login-test <condomínio>` | faz login no ISSNet, confere o CNPJ na página e salva screenshot em `debug/` |
| `condosys recon <condomínio>` | login + Playwright Inspector; salva HTML/screenshot de cada tela em `debug/recon/` |
| `condosys adn-test <condomínio>` | uma consulta à API do ADN (acesso DIRETO); salva a resposta em `debug/adn/` |
| `condosys adn-notas <condomínio> -c 09/2026` | baixa as notas novas do ADN e lista as tomadas na competência (`--cert` para o CNPJ do certificado) |

Todos os comandos aceitam `--help`. Use `uv run condosys -v <comando>` para log detalhado.

`<condomínio>` aceita o nome (ou parte dele, sem acento/maiúscula) ou o CNPJ.

## Como o condosys acessa as notas

> **Importante (23/10/2026):** o iHub, que faz o login do ISSNet, bloqueou o acesso
> automatizado e orientou usar o webservice do sistema (Ref. 568F9D19). A automação do
> portal está **desligada** até o suporte autorizar (ver ADR-010 em
> [docs/decisoes.md](docs/decisoes.md)). O caminho ativo é a API oficial do ADN.

- **Procuração (Sema, i9) — login assistido no portal ISSNet.** O login do portal passa por
  uma janela do iHub protegida pelo Cloudflare, que barra navegadores automatizados. Então
  **uma pessoa faz o login** no Chrome/Edge comum (escolhe o certificado, marca "Confirme
  que é humano" se aparecer) e o condosys assume o navegador quando o portal abre. Um login
  por certificado; cada login consome saldo da licença do portal no iHub.
- **Direto (certificado do próprio condomínio) — API oficial do ADN** (Ambiente de Dados
  Nacional da NFS-e), sem navegador.

Antes do primeiro login assistido, instale os certificados de procuração no navegador
(uma vez por computador; no Linux precisa de `sudo apt install libnss3-tools`):

```bash
uv run condosys cert install sema.pfx
```

Teste:

```bash
uv run condosys login-test "Condomínio do Edifício Vivendas 107"   # procuração
uv run condosys adn-test "the sun"                                  # direto
```

Resultado do `login-test`: tabela com a página aberta, se o CNPJ/nome do condomínio
aparece e o caminho do screenshot. Código de saída 0 = confirmado, 1 = erro, 2 = entrou
mas não achou o CNPJ. Passo a passo completo em [docs/guia-de-testes.md](docs/guia-de-testes.md).

### Recon (mapear as telas)

```bash
uv run condosys recon "the sun"
```

1. Faça o login na janela que abrir; o condosys assume e abre o **Playwright Inspector**.
2. Navegue: Menu → Declaração de Serviços Contratados → Consulta de Notas Tomadas;
   preencha os filtros (NFS-e, datas da competência, Status Normal), clique em Localizar,
   abra uma nota (Visualizar), teste o ícone ao lado (XML?), vá para a página 2 da grade.
3. Cada página carregada é salva sozinha. Depois de **Localizar** e de qualquer mudança
   sem recarregar a página, clique no botão **Capturar** (canto inferior direito).
4. No Inspector, **Pick locator** mostra o seletor de qualquer elemento.
5. Clique em **Resume** (▶) para seguir sem o Inspector; feche as abas para terminar.

Tudo fica em `debug/recon/<data-hora>/`: `NNN_*.html`, `NNN_*.png`, `index.jsonl`,
`requests.log` e `downloads/`. `--trace` grava também um `trace.zip` (abrir com
`uv run playwright show-trace debug/recon/<data-hora>/trace.zip`; contém cookies).

## Segurança e dados sensíveis

- `.pfx` ficam só em `certs/`, que **não** vai para o git. Senhas ficam só no cofre do sistema.
- O sistema nunca grava senhas, conteúdo de certificados ou cookies em arquivos ou logs.
- `debug/` (screenshots e HTML) e `output/` **contêm dados fiscais** dos condomínios: não
  compartilhe nem versione. Ambas as pastas estão no `.gitignore`.
- `config/condominios.xlsx` (lista real de clientes) também fica fora do git.
- Respeito ao portal: um condomínio por vez, pausas entre ações, sem paralelismo.

## Desenvolvimento

```bash
uv run pytest              # testes (os de navegador usam servidores locais)
uv run pytest -m "not browser"   # sem Chromium
uv run ruff check .        # lint
uv run ruff format .       # formatação
uv run mypy                # tipos (strict)
```

Guia completo de testes (instalação, roteiro manual, recon, erros comuns): [docs/guia-de-testes.md](docs/guia-de-testes.md).

Documentação técnica: [docs/arquitetura.md](docs/arquitetura.md),
[docs/decisoes.md](docs/decisoes.md), [docs/issnet-mapa.md](docs/issnet-mapa.md) e a rotina
original em [docs/rotina-fiscal.pdf](docs/rotina-fiscal.pdf).
