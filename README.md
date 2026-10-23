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
| `condosys config check` | valida `condominios.xlsx` e cruza com os certificados |

Todos os comandos aceitam `--help`. Use `uv run condosys -v <comando>` para log detalhado.

## Segurança e dados sensíveis

- `.pfx` ficam só em `certs/`, que **não** vai para o git. Senhas ficam só no cofre do sistema.
- O sistema nunca grava senhas, conteúdo de certificados ou cookies em arquivos ou logs.
- `debug/` (screenshots e HTML) e `output/` **contêm dados fiscais** dos condomínios: não
  compartilhe nem versione. Ambas as pastas estão no `.gitignore`.
- `config/condominios.xlsx` (lista real de clientes) também fica fora do git.
- Respeito ao portal: um condomínio por vez, pausas entre ações, sem paralelismo.

## Desenvolvimento

```bash
uv run pytest              # testes
uv run ruff check .        # lint
uv run ruff format .       # formatação
uv run mypy                # tipos (strict)
```

Documentação técnica: [docs/arquitetura.md](docs/arquitetura.md),
[docs/decisoes.md](docs/decisoes.md), [docs/issnet-mapa.md](docs/issnet-mapa.md) e a rotina
original em [docs/rotina-fiscal.pdf](docs/rotina-fiscal.pdf).
