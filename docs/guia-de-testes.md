# Guia de testes do condosys

Como instalar, testar e validar o condosys no **Linux** e no **Windows**. Cobre a
versão reformulada (ADR-011): notas pelo ADN, planilha da coleta, API local e interface
Electron. A versão anterior, baseada no portal ISSNet, está no histórico do git.

## 1. Visão geral

| tipo | cobre | certificado real? | acessa a internet? |
|---|---|---|---|
| **Automatizados** (`pytest`) | CNPJ, modelos, planilha de condomínios, `.pfx`, cofre (em memória), CLI, ADN com servidor mTLS local, sincronização, leitura do XML nacional, coleta em lote, Excel, API local | não | não |
| **Manuais** | cadastro dos certificados reais, coleta real no ADN, interface | sim | sim (ADN) |

Os testes nunca usam o cofre de senhas real (`tests/conftest.py` troca por um cofre em
memória) nem o ADN de verdade.

## 2. Instalação

### Linux (Debian)

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
cd ~/Documents/Workspace/Pessoal/condosys
uv sync
uv run condosys init
cd desktop && npm install
```

O GNOME Keyring ou o KWallet precisa estar desbloqueado. Para conferir:
`uv run python -c "import keyring; print(keyring.get_keyring())"`, que deve mostrar
`SecretService.Keyring`.

### Windows

```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
# instale também o Node.js LTS: https://nodejs.org
git clone <url-do-repositorio> condosys
cd condosys
uv sync
uv run condosys init
cd desktop; npm install
```

As senhas ficam no Gerenciador de Credenciais (entradas `condosys`).

## 3. Testes automatizados

```bash
uv run pytest                       # tudo (~10 s)
uv run pytest tests/test_api.py -v  # um arquivo
uv run ruff check . && uv run ruff format --check . && uv run mypy
```

| arquivo | cobre |
|---|---|
| `test_models.py` | CNPJ numérico/alfanumérico, valores em reais → `Decimal`, competência, condomínio |
| `test_config_loader.py` | planilha de condomínios: variações de cabeçalho, erros por linha/coluna, duplicados, coluna antiga `modo_acesso` ignorada, gravação |
| `test_certificates.py` | titular/CNPJ ICP-Brasil, vencido, senha errada, `.pfx` legado, cofre |
| `test_cli.py` | `init`, `cert add/list/remove`, `config sync` (contabilidade entra inativa), `config check` (certificado de outro CNPJ) |
| `test_adn.py` | consulta com mTLS contra servidor local, raiz do CNPJ, extração dos XML |
| `test_adn_sync.py` | paginação por NSU, retomada, NSU repetido, erro HTTP, filtro tomador/competência, comando `notas` |
| `test_nfse_nacional.py` | leitura do XML nacional (fixture sintética em `tests/fixtures/`) |
| `test_collect_export.py` | coleta em lote com falha num condomínio, planilha gerada (todas as abas e valores) |
| `test_api.py` | token obrigatório, certificados, sincronização, edição de condomínio, coleta assíncrona, planilhas |

## 4. Roteiro manual

### 4.1 Certificados

Os certificados já copiados para `certs/` precisam da senha cadastrada, uma vez por
computador.

Pela interface: **Certificados → Cadastrar senha** em cada linha, ou **Adicionar
certificado** para um arquivo de outra pasta.

Pelo terminal:

```bash
uv run condosys cert add "certs/MADISON - VAL. 18.03.2027.pfx"
uv run condosys cert add "certs/Satélite - Venc. 13.01.2027.pfx"
uv run condosys cert add "certs/Terracota - venci. 15.12.2026.pfx"
uv run condosys cert list
```

Esperado: titular, CNPJ, validade e "ok". Senha errada: "senha incorreta ou arquivo
inválido" e nada é gravado.

### 4.2 Condomínios

```bash
uv run condosys config sync
uv run condosys config check
```

Esperado: um condomínio por certificado. Um certificado da contabilidade (ex.: Sema)
entra como inativo, com a observação "verificar". O `check` acusa erro quando o
certificado de um condomínio é de outro CNPJ. Exemplo: a linha antiga do Vivendas 107
com `sema.pfx` fica marcada até ganhar o certificado próprio.

### 4.3 Notas de um condomínio

```bash
uv run condosys notas "madison" -c 09/2026
```

A primeira vez baixa o histórico do condomínio no ADN: 50 documentos por consulta, com
1 s de pausa. As seguintes buscam só as notas novas. Os XML ficam em `data/adn/<CNPJ>/`.

### 4.4 Coleta do mês

Pela interface: **Coleta do mês** → escolha o mês → **Coletar notas de …** → **Abrir
planilha**.

Pelo terminal:

```bash
uv run condosys coletar -c 09/2026
```

Confira na planilha:
- **Notas:** número, prestador, valores, retenções, líquido e chave de acesso batem com
  as notas.
- **Resumo:** um condomínio por linha. **Erros:** vazia, ou com o motivo claro.
- **Controle PIS:** notas com PIS/COFINS/CSLL retido. **Controle INSS:** notas com INSS
  retido e base = retido ÷ 0,11. **Controle ISSQN:** ISS retido ou serviço fora de
  Brasília.

### 4.5 Interface

```bash
cd desktop
npm start                                   # Windows
env -u ELECTRON_RUN_AS_NODE npm start       # Linux, dentro do terminal do VS Code
npm run screenshot                          # salva as 4 telas em debug/ui/ e fecha
```

Confira:
1. O rodapé da barra lateral mostra "Conectado".
2. Fechar a janela encerra o backend: não pode sobrar processo `condosys serve`.
3. Certificados com menos de 30 dias aparecem em âmbar; vencidos, em vermelho.
4. Durante a coleta, a barra de progresso e os detalhes avançam e o botão fica
   desabilitado.

## 5. Erros comuns

| mensagem | causa | o que fazer |
|---|---|---|
| `senha do certificado X não cadastrada` | senha não está no cofre deste computador | Certificados → Cadastrar senha |
| `o ADN exige a mesma raiz de CNPJ` / "certificado de outro CNPJ" | linha do condomínio aponta para o certificado de outra empresa | trocar pelo certificado do próprio condomínio |
| `certificado vencido em …` | A1 vencido | renovar o certificado |
| `ainda há documentos a baixar no ADN` | histórico grande (mais de 100 lotes) | rodar a coleta de novo; ela continua de onde parou |
| `ADN respondeu HTTP 4xx` | certificado recusado ou parâmetro inválido | `condosys adn-test "<condomínio>"` e trazer `debug/adn/<data-hora>/resposta.txt` |
| `Não foi possível acessar o cofre de senhas` | Linux sem cofre desbloqueado | desbloquear o GNOME Keyring/KWallet |
| interface "Sem conexão" | `uv` fora do PATH ou backend com erro | rodar `uv run condosys serve` no terminal e ler o erro |
| Electron abre como Node (`Cannot read properties of undefined (reading 'handle')`) | `ELECTRON_RUN_AS_NODE` definido (terminal do VS Code) | `env -u ELECTRON_RUN_AS_NODE npm start` |

## 6. Cuidados

- `data/`, `output/`, `logs/` e `debug/` têm dados fiscais: não compartilhe.
- Senhas só no cofre do sistema; nunca no `.env` nem em mensagens.
- Uma coleta por vez. O ADN é consultado com pausas, sem paralelismo.
- Nada é transmitido à Receita nesta versão. Reinf, DCTFWeb e DARF virão com
  confirmação explícita.

## 7. Checklist de aceite (reformulação)

- [ ] `uv run pytest`, `ruff` e `mypy` sem erros
- [ ] Senhas dos 3 certificados cadastradas; `cert list` mostra titular/CNPJ corretos
- [ ] `config sync` cria os 3 condomínios ativos; `config check` sem erro para eles
- [ ] `coletar -c MM/AAAA` gera a planilha; valores conferidos com uma nota real
- [ ] Interface: cadastro de senha, sincronização, coleta e "Abrir planilha" funcionam
- [ ] Testado no Linux e no Windows
