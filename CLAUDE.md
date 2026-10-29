# CLAUDE.md — condosys

Rotina fiscal dos condomínios atendidos pelo escritório (DF): notas de serviço tomadas
pela API oficial do **ADN** (NFS-e nacional) com o certificado A1 de **cada
condomínio**; planilha da coleta (Notas, Resumo, Erros, Controles PIS/INSS/ISSQN);
próximas fases: pré-análise de retenções, Google Sheets, EFD-Reinf, DCTFWeb/DARF via
Integra Contador. Interface em **Electron** (`desktop/`) sobre uma API local em Python.
Usuários finais em **Windows**; desenvolvimento em **Linux**. Rotina original:
`docs/rotina-fiscal.pdf`. Fases: `ROADMAP.md`.

## Comandos

```bash
uv sync
uv run condosys --help
uv run pytest
uv run ruff check . && uv run ruff format --check .
uv run mypy                                   # strict no pacote
cd desktop && npm install && npm start        # interface (Linux/VS Code: env -u ELECTRON_RUN_AS_NODE npm start)
cd desktop && npm run screenshot              # telas em debug/ui/ para revisão visual
```

Antes de concluir qualquer mudança: `ruff check`, `ruff format`, `mypy` e `pytest` passando.

## Arquitetura (resumo)

- `cli.py` (Typer) e `api.py` (FastAPI local) → `services/` (certificates, condominiums, collect, adn_invoices) → `adn.py` (mTLS, NSU, `data/adn/<CNPJ>/`), `nfse_nacional.py` (parser puro), `exporters/excel.py`.
- `certificates.py` (cryptography) lê `.pfx`; `credentials.py` (keyring) guarda senhas; `config_loader.py` lê/grava `config/condominios.xlsx` (sem `modo_acesso`).
- `desktop/`: `main.js` inicia `condosys serve --port 0` com token em `CONDOSYS_API_TOKEN`; `preload.js` é a única ponte; `renderer/` é HTML/CSS/JS sem build. Página isolada (sandbox, sem Node).
- Decisões: `docs/decisoes.md` (ADR-010: iHub bloqueou automação; ADR-011: só APIs oficiais). Layout do ADN: `docs/adn.md`.

## Regras

- **Sem web scraping, sem automação de portal, nunca contornar verificações anti-robô.** Só APIs oficiais (ADN, EFD-Reinf, Integra Contador, Google Sheets).
- Transmissões com efeito legal/financeiro (Reinf, DCTFWeb, DARF): gerar → revisar → confirmação explícita da pessoa → transmitir; primeiro em produção restrita.
- O sistema sinaliza, o funcionário decide: valores das abas de controle são propostas.

## Convenções

- Identificadores, comentários inline e docstrings (Google) em **inglês**; documentação e mensagens ao usuário em **português**.
- Type hints em tudo (mypy strict). Parsers puros testados com fixtures em `tests/fixtures/` (sintéticas ou anonimizadas).
- Dinheiro sempre `Decimal`; datas como `date`. CNPJ normalizado internamente (`documents.normalize_cnpj`, aceita alfanumérico), formatado só na saída.
- Caminhos com `pathlib`; nomes de arquivo sem `:` (Windows).
- Interface: textos em português, frase com maiúscula só no início; DOM montado com `textContent` (nunca `innerHTML` com dados).

## Segurança

- `.pfx` só em `certs/`; senhas só no keyring. Nunca em arquivo, código, log ou resposta da API.
- `data/`, `output/`, `logs/`, `debug/` têm dados fiscais: fora do git.
- API local só em 127.0.0.1, sempre com token; a interface só abre arquivos dentro da pasta do condosys.
- ADN: uma consulta por vez, com pausa; sem paralelismo.
- Testes nunca usam o cofre real nem serviços reais.

## Ao concluir uma fase

Atualizar `ROADMAP.md`, `docs/guia-de-testes.md` e `docs/decisoes.md`; um commit por fase em português.
