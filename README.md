# condosys

Sistema do departamento fiscal para os condomínios atendidos pelo escritório no DF.
Todo mês ele baixa as **notas de serviço tomadas** de cada condomínio pela API oficial do
**Ambiente de Dados Nacional da NFS-e (ADN)**, com o certificado A1 do próprio
condomínio, e gera a planilha da competência com as notas, o resumo e as propostas de
lançamento nos controles de PIS/COFINS/CSLL, INSS e ISSQN.

Próximas etapas (ver [ROADMAP.md](ROADMAP.md)): pré-análise das retenções, Google
Sheets, EFD-Reinf e DCTFWeb/DARF pelo Integra Contador (Serpro). O sistema não usa mais
o portal ISSNet nem automação de navegador ([docs/decisoes.md](docs/decisoes.md),
ADR-010 e ADR-011).

Funciona no **Windows** (uso diário) e no **Linux**.

## Instalação (desenvolvimento)

Requisitos: [uv](https://docs.astral.sh/uv/) e, para a interface, Node.js 20+.

```bash
# Linux
curl -LsSf https://astral.sh/uv/install.sh | sh
# Windows (PowerShell)
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"

cd condosys
uv sync
uv run condosys init          # pastas, .env e planilha de exemplo
cd desktop && npm install     # interface
```

## Uso pela interface

```bash
cd desktop
npm start
```

A janela abre e inicia o backend sozinha. Telas:

- **Certificados:** adicione o `.pfx` de cada condomínio ou cadastre a senha dos que já
  estão na pasta `certs/`. A senha fica no cofre do sistema (Gerenciador de Credenciais
  no Windows). A tela mostra a validade e avisa quando faltam menos de 30 dias.
- **Condomínios:** "Atualizar a partir dos certificados" cria um condomínio para cada
  certificado novo. Desmarque "Ativo" para tirar um condomínio da coleta.
- **Coleta do mês:** escolha a competência (o padrão é o mês anterior), confira os
  condomínios e clique em "Coletar notas de ...". Ao final, "Abrir planilha".
- **Planilhas geradas:** histórico das planilhas em `output/`.

No Linux, rode `npm start` num terminal sem a variável `ELECTRON_RUN_AS_NODE` (o
terminal do VS Code a define): `env -u ELECTRON_RUN_AS_NODE npm start`.

## Uso pelo terminal

| comando | o que faz |
|---|---|
| `condosys init` | cria pastas, `.env` e `config/condominios.example.xlsx` |
| `condosys cert add <arquivo.pfx> [--name x.pfx]` | valida o certificado, guarda a senha no cofre e copia para `certs/` |
| `condosys cert list` | certificados com titular, CNPJ, validade e senha |
| `condosys cert remove <nome>` | apaga a senha do cofre (o arquivo fica) |
| `condosys config sync` | inclui na planilha os condomínios dos certificados de `certs/` |
| `condosys config check` | valida a planilha e confere se cada certificado é do CNPJ do condomínio |
| `condosys notas "<condomínio>" -c 09/2026` | lista as notas tomadas de um condomínio |
| `condosys coletar -c 09/2026 [--condominio X]` | coleta todos os ativos e gera `output/notas_2026-09_<data-hora>.xlsx` |
| `condosys adn-test "<condomínio>"` | uma consulta bruta ao ADN, salva em `debug/adn/` (diagnóstico) |
| `condosys serve` | API local usada pela interface |

Cadastrar as senhas dos certificados que já estão em `certs/`:

```bash
uv run condosys cert add "certs/MADISON - VAL. 18.03.2027.pfx"
uv run condosys config sync
uv run condosys coletar -c 09/2026
```

## Planilha de condomínios (`config/condominios.xlsx`)

| coluna | descrição |
|---|---|
| `ativo` | SIM/NÃO |
| `nome` | nome do condomínio |
| `cnpj` | CNPJ (com ou sem pontuação; aceita o CNPJ alfanumérico) |
| `certificado` | arquivo `.pfx` do próprio condomínio em `certs/` |
| `observacoes` | texto livre |

O `config sync` (ou o botão da interface) preenche a planilha a partir dos certificados.
Certificados cujo titular não parece um condomínio (ex.: a própria contabilidade) entram
como inativos, para conferência.

## Planilha da coleta

`output/notas_<AAAA-MM>_<data-hora>.xlsx`:

- **Notas:** uma linha por nota, com retenções, valor líquido, chave de acesso e as
  referências de 4,65% (PIS/COFINS/CSLL) e base do INSS (retido ÷ 0,11).
- **Resumo:** totais por condomínio. **Erros:** condomínios que falharam e o motivo.
- **Controle PIS / Controle INSS / Controle ISSQN:** linhas no formato das planilhas de
  controle do setor (rotina fiscal, seção 6), prontas para conferir e lançar. São
  propostas: o sistema sinaliza, o funcionário decide.

## Segurança e dados sensíveis

- Certificados só em `certs/`, senhas só no cofre do sistema. Nada disso vai para o git.
- `data/` (XML baixados), `output/`, `logs/` e `debug/` contêm dados fiscais e ficam
  fora do git. Não envie por e-mail ou chat.
- A API local escuta só em `127.0.0.1` e exige um token gerado pela interface a cada
  execução.
- Etapas que transmitem para a Receita (Reinf, DCTFWeb, DARF) sempre pedirão
  confirmação explícita na interface.

## Desenvolvimento

```bash
uv run pytest
uv run ruff check . && uv run ruff format --check .
uv run mypy
```

Guia de testes: [docs/guia-de-testes.md](docs/guia-de-testes.md). Arquitetura:
[docs/arquitetura.md](docs/arquitetura.md). ADN: [docs/adn.md](docs/adn.md).
