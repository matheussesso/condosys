# Arquitetura

## Visão geral

```
condosys (CLI Typer)
   │
   ├── config_loader ──► config/condominios.xlsx  (quais condomínios, qual certificado)
   ├── certificates  ──► certs/*.pfx               (titular, CNPJ, validade)
   ├── credentials   ──► cofre do sistema (keyring)
   │
   └── services/collect (orquestração, um condomínio por vez)
          │
          ├── browser            um BrowserContext por certificado (client_certificates)
          ├── portals/issnet
          │     ├── session        login, seleção do contribuinte, conferência, logout
          │     ├── invoices_page  Consulta de Notas Tomadas (navega, devolve HTML)
          │     ├── parsers        HTML/XML → modelos (funções puras)
          │     └── selectors      todos os seletores do portal
          └── exporters/excel    output/notas_<competencia>_<data-hora>.xlsx
```

## Módulos

| módulo | responsabilidade |
|---|---|
| `cli.py` | comandos Typer, saída Rich; nenhuma regra de negócio pesada |
| `settings.py` | configurações (`CONDOSYS_*`, `.env`); caminhos relativos à pasta do projeto |
| `logging_setup.py` | console Rich + `logs/condosys.log` rotativo (2 MB × 5) |
| `models.py` | modelos Pydantic v2; `Money` (aceita `"1.234,56"`, recusa `float`) |
| `documents.py` | CNPJ: normalização, dígitos verificadores (inclusive alfanumérico), formatação |
| `config_loader.py` | lê/valida a planilha, erros por linha/coluna, busca por nome/CNPJ, gera o exemplo |
| `certificates.py` | abre `.pfx`, extrai dados públicos, recodifica PKCS#12 em memória |
| `credentials.py` | senha do `.pfx` no keyring (serviço `condosys`, conta `pfx:<arquivo>`) |
| `browser.py` | Playwright: lançar navegador, criar contexto com certificado |
| `portals/issnet/*` | Page Objects e parsers do ISSNet DF |
| `exporters/excel.py` | planilha de saída (Fase 4) |
| `services/collect.py` | fluxo completo por condomínio, erros não interrompem o lote (Fases 2–4) |

## Princípios

1. **Navegação ≠ parsing.** Page Objects só clicam, preenchem e devolvem HTML/bytes.
   Parsers são funções puras testadas com HTML real salvo em `tests/fixtures/`.
2. **Seletores num só lugar** (`selectors.py`), preenchidos a partir do recon, nunca inventados.
3. **Isolamento por certificado.** Cada condomínio (ou cada certificado de procuração)
   usa um `BrowserContext` novo: sem cookies, cache ou certificado de outra sessão. Isso
   resolve o problema atual de "trocar certificado / fechar sessão" no Edge.
4. **Falha isolada.** Na coleta em lote, um condomínio com erro vira uma linha na aba
   "Erros" e o lote continua.
5. **Portal respeitado.** Sequencial, `slow_mo`, timeouts e pausas configuráveis.

## Fluxo de login (Fase 1)

1. `config_loader` encontra o condomínio e o arquivo do certificado.
2. `credentials` lê a senha do keyring; `certificates` abre o `.pfx` e (por padrão)
   recodifica o PKCS#12 em memória com AES-256.
3. `browser` cria o contexto com
   `client_certificates=[{"origin": "https://api.ihub.com.br", "pfx": <bytes>, "passphrase": <aleatória>}]`.
4. `session` abre a página de login, confere se os scripts do portal carregaram e clica
   em `#btnAcionaCertificado`. O portal abre um popup em `api.ihub.com.br/auth`, onde o
   navegador apresenta o certificado no handshake TLS (sem janela de seleção); o popup
   devolve um ticket e a página entra no portal. Erros de TLS no popup e `alert()` do
   portal interrompem o login na hora (ADR-007).
5. Procuração: seleção do contribuinte no cabeçalho (seletor a capturar no recon; até lá
   o usuário escolhe manualmente na janela e confirma no terminal).
6. Conferência: o CNPJ/nome do condomínio deve aparecer na página (cabeçalho).

## Multiplataforma

- Caminhos com `pathlib`; nomes de arquivo sem `:`; arquivos de texto em UTF-8.
- Keyring: Credential Manager (Windows) e Secret Service (Linux).
- Navegador: Chromium do Playwright nos dois sistemas; opcionalmente o Edge instalado
  (`CONDOSYS_BROWSER_CHANNEL=msedge`) no Windows. Sempre com janela visível (o Cloudflare
  bloqueia o modo invisível).
- Distribuição futura: executável PyInstaller (Fase 8).
