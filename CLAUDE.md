# CLAUDE.md — condosys

Automação da rotina fiscal de condomínios no DF: login no portal **ISSNet On-Line** com
certificado A1 (`.pfx`), consulta de Notas Tomadas, detalhe das notas e exportação para
Excel. Usuários finais em **Windows**; desenvolvimento em **Linux**. Tudo deve rodar nos dois.
Rotina original: `docs/rotina-fiscal.pdf`. Fases: `ROADMAP.md`.

## Comandos

```bash
uv sync                                   # dependências
uv run playwright install chromium        # navegador
uv run condosys --help                    # CLI
uv run pytest                             # testes (inclui os de navegador, marcador "browser")
uv run pytest -m "not browser"            # sem Chromium
uv run ruff check . && uv run ruff format --check .
uv run mypy                               # strict no pacote
```

Antes de concluir qualquer mudança: `ruff check`, `ruff format`, `mypy` e `pytest` passando.

## Arquitetura (resumo)

- `cli.py` (Typer) → `services/` (orquestração) → `portals/issnet/` (Page Objects) + `parsers.py` (puro) → `exporters/`.
- `browser.py`: um `BrowserContext` novo **por certificado**, com `client_certificates` do Playwright.
- Login do ISSNet: popup `https://api.ihub.com.br/auth` pede o certificado no TLS (ADR-007). O Cloudflare reprova navegador automatizado: o padrão é o **login assistido** (`assisted_browser.py`, ADR-009) — pessoa loga no Chrome/Edge comum, condosys conecta via CDP depois. Nunca tentar contornar a verificação. Cada login debita saldo no iHub.
- Acesso DIRETO: API oficial do ADN (`adn.py`), mTLS, certificado com mesma raiz de CNPJ. Layout real e mapeamento em `docs/adn.md`.
- `recon.py`: gravador de páginas para o recon (`debug/recon/<timestamp>/`).
- `certificates.py` (cryptography) lê `.pfx`; `credentials.py` (keyring) guarda senhas; `config_loader.py` lê `config/condominios.xlsx`.
- `settings.py` (pydantic-settings, prefixo `CONDOSYS_`, `.env`); `models.py` (Pydantic v2).
- Detalhes em `docs/arquitetura.md`; decisões em `docs/decisoes.md`.

## Convenções

- Identificadores, comentários inline e docstrings (estilo Google) em **inglês**; documentação (`README.md`, `docs/`, `ROADMAP.md`, este arquivo) e mensagens ao usuário em **português**.
- Type hints em tudo (mypy strict).
- **Navegação separada de parsing**: Page Objects só navegam e devolvem HTML/dados brutos; parsers são funções puras (HTML/XML → modelos Pydantic), testadas com fixtures em `tests/fixtures/`.
- Seletores centralizados em `portals/<portal>/selectors.py`, nunca espalhados.
- **Nunca inventar seletores.** Usar o material de `debug/recon/` e `docs/issnet-mapa.md`; se faltar, deixar `TODO: capturar via recon` e explicar como obter.
- Dinheiro sempre `Decimal` (nunca `float`); datas como `date`.
- CNPJ normalizado internamente (`documents.normalize_cnpj`; aceita o CNPJ alfanumérico), formatado só na saída.
- Caminhos com `pathlib`; nomes de arquivo sem `:` (Windows).

## Segurança

- `.pfx` só em `certs/` (fora do git). Senhas só no keyring. Nunca em arquivo, código ou log.
- Nunca logar senhas, conteúdo de certificados nem cookies de sessão.
- `debug/` e `output/` contêm dados fiscais: fora do git; não copiar para fixtures sem anonimizar CNPJs/nomes de terceiros quando possível.
- Respeitar o portal: um condomínio por vez, pausas curtas (`slow_mo_ms`), timeouts configuráveis, sem paralelismo.
- Testes nunca usam o cofre real (`tests/conftest.py` troca por um keyring em memória).

## Ao concluir uma fase

Sempre atualizar `ROADMAP.md` (checklist), `docs/guia-de-testes.md` (roteiro da fase) e `docs/decisoes.md` (decisões e problemas encontrados), e fazer um commit por fase com mensagem clara em português.
