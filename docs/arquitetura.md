# Arquitetura

```
 Electron (desktop/)                      Python (src/condosys/)
 ┌──────────────────────┐   HTTP local   ┌───────────────────────────────────────────┐
 │ renderer/ (tela)     │ ─────────────► │ api.py (FastAPI, 127.0.0.1, token)        │
 │ preload.js (ponte)   │   + token      │ cli.py (Typer)                            │
 │ main.js (processo)   │ ── inicia ───► │      │                                    │
 └──────────────────────┘ condosys serve │      ▼                                    │
                                         │ services/  certificates · condominiums ·  │
                                         │            collect · adn_invoices         │
                                         │      │                                    │
                                         │      ▼                                    │
                                         │ adn.py ── mTLS ──► adn.nfse.gov.br        │
                                         │ nfse_nacional.py (XML → InvoiceDetail)    │
                                         │ exporters/excel.py (planilha da coleta)   │
                                         │ certificates.py · credentials.py (cofre)  │
                                         │ config_loader.py (condominios.xlsx)       │
                                         └───────────────────────────────────────────┘
```

## Camadas

- **`services/`**: regras de uso compartilhadas pela CLI e pela API. Nenhuma tela chama
  `adn.py` ou o cofre diretamente.
- **`adn.py`**: cliente da API de distribuição do ADN. Uma consulta por vez, pausa entre
  lotes, sincronização incremental por NSU, armazenamento em `data/adn/<CNPJ>/`.
- **`nfse_nacional.py`**: parser puro do XML nacional, testado com fixture sintética.
- **`exporters/excel.py`**: planilha da coleta (Notas, Resumo, Erros, controles).
- **`api.py`**: API local. Coletas rodam numa thread, uma de cada vez; a tela acompanha
  por consulta periódica (`GET /api/jobs/{id}`).

## Fluxo da coleta

1. A planilha de condomínios lista CNPJ e arquivo do certificado de cada condomínio.
2. Para cada condomínio ativo, um por vez: a senha sai do cofre, o `.pfx` é aberto em
   memória, e o ADN é consultado com mTLS a partir do último NSU baixado.
3. Os XML novos vão para `data/adn/<CNPJ>/`. Ficam ali as notas em que o condomínio é
   tomador, emitidas dentro da competência.
4. Uma falha num condomínio vai para a aba "Erros" e a coleta segue.
5. Ao final, a planilha é gravada em `output/`.

## Interface (Electron)

- `main.js` inicia `condosys serve --port 0` (em desenvolvimento, via `uv run`) com um
  token aleatório em `CONDOSYS_API_TOKEN` e espera a linha `{"event":"ready","port":N}`.
- O backend termina quando a interface fecha: ela fecha o stdin dele
  (`CONDOSYS_EXIT_ON_STDIN_EOF=1`). No Windows a árvore de processos é encerrada com
  `taskkill /T`.
- A página roda isolada (`contextIsolation`, `sandbox`, sem Node). O acesso ao sistema
  operacional (escolher arquivo, abrir planilha) passa pelo `preload.js`. Só abre
  arquivos dentro da pasta do condosys.
- Distribuição (fase 9): backend empacotado com PyInstaller em `resources/backend/`, e o
  instalador gerado com electron-builder.

## Multiplataforma

- Caminhos com `pathlib`, nomes de arquivo sem `:`, UTF-8 em todos os textos.
- Cofre: Gerenciador de Credenciais (Windows) e Secret Service (Linux).
- Fontes da interface: Bahnschrift e Segoe UI (Windows). No Linux, as equivalentes do
  sistema.

## Próximas integrações

- **EFD-Reinf** (R-2010, R-4020, R-2099/R-4099): webservice oficial com o certificado do
  condomínio, sempre primeiro em produção restrita.
- **Integra Contador** (Serpro): DCTFWeb e DARF.
- **Google Sheets**: conta de serviço, lançamento só de notas aprovadas.
