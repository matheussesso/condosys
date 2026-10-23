# Roadmap — condosys

Construção incremental. Ao concluir uma fase: marcar aqui, registrar decisões em
[docs/decisoes.md](docs/decisoes.md) e fazer um commit por fase.

## Fase 0 — Fundação ✅

- [x] Projeto Python 3.12 com uv, layout `src/`, ruff, mypy strict, pytest
- [x] Settings (`pydantic-settings`, `.env`), logging (Rich + arquivo rotativo em `logs/`)
- [x] Modelos: `Condominium`, `CertificateInfo`, `Competence`, `Invoice`, `InvoiceDetail`, `Flag`, `RunResult`
- [x] CNPJ: validação (numérico e alfanumérico), normalização e formatação
- [x] Leitura e validação de `config/condominios.xlsx` com erros por linha/coluna
- [x] Leitura de `.pfx` (titular, CNPJ ICP-Brasil, emissor, validade)
- [x] Senhas no keyring (Windows Credential Manager / Secret Service)
- [x] CLI: `init`, `cert add|list|remove`, `config check`
- [x] Esqueletos (`NotImplementedError`) de consulta, parsing, exportação e orquestração
- [x] Documentação: README, CLAUDE.md, arquitetura, decisões, mapa do ISSNet

## Fase 1 — Login e recon ✅ (código) — aguardando teste no portal real

- [x] Fábrica de navegador com `client_certificates` (um contexto por certificado, `.pfx` recodificado em memória)
- [x] Descoberta do fluxo real: popup `api.ihub.com.br` pede o certificado (ADR-007)
- [x] Login no ISSNet (popup, alertas, erro TLS, scripts bloqueados) e conferência do CNPJ na página
- [x] Seleção do contribuinte (procuração): passo manual guiado até o recon capturar o seletor
- [x] `condosys login-test <condomínio>` com screenshot em `debug/`
- [x] `condosys recon <condomínio>`: Playwright Inspector + captura automática (HTML, frames, screenshot, requisições, downloads, botão "Capturar", `--trace`)
- [x] Testes com servidores locais (mTLS, popup iHub falso, gravador)
- [x] Primeiro teste real (Sema): certificado chega ao iHub; Cloudflare reprova o navegador automatizado (ADR-009)
- [x] Login assistido: Chrome/Edge comum + certificado instalado (`cert install`), condosys assume após o login
- [x] `condosys adn-test`: consulta única à API do ADN para acesso DIRETO
- [x] Login assistido testado com a Sema: Chrome comum → tela Empresas (23/10/2026)
- [x] `adn-test` em produção: HTTP 200, 50 NFS-e do DF (docs/adn.md)
- [x] Seleção automática da empresa (filtro por CNPJ + ✓) e navegação até Consulta de Notas Tomadas — seletores provisórios
- [x] Seleção automática da empresa validada no portal real (23/10/2026); filtros da consulta confirmados no HTML
- [ ] ~~Validar a consulta pelo portal~~ — **suspenso**: o iHub bloqueou acesso automatizado e pediu o webservice (ADR-010, Ref. 568F9D19)
- [ ] Contatar o suporte do ISSNet com a Ref. 568F9D19 (webservice para notas tomadas via procuração)
- [ ] Preencher `selectors.py` e `docs/issnet-mapa.md` com o material do recon

## Fase 2 — Consulta de notas

- [ ] Navegar até Consulta de Notas Tomadas (menu ou URL direta)
- [ ] Filtros: Série NFS-e, Data Emissão Inicial/Final da competência, Status Normal, Localizar
- [ ] Ler a grade "Documentos Fiscais" com paginação
- [ ] `parse_invoice_grid` testado com fixtures HTML do recon (`tests/fixtures/`)

## Fase 3 — Detalhe das notas

- [ ] Abrir cada nota ("Visualizar") e extrair `InvoiceDetail`
- [ ] Verificar se o ícone ao lado de "Visualizar" baixa o **XML** — se sim, preferir XML a HTML
- [ ] **ADN para acesso DIRETO**: paginação por NSU, parsing do XML nacional, filtro por competência
      (consulta confirmada em produção em 23/10/2026 — ver `docs/adn.md`; procuração não é aceita pelo ADN)

## Fase 4 — Exportação Excel

- [ ] Aba "Notas" (uma linha por nota, todos os campos)
- [ ] Aba "Resumo" (por condomínio: quantidade de notas, totais)
- [ ] Aba "Erros" (condomínios que falharam e o motivo)
- [ ] Arquivo `output/notas_<competencia>_<data-hora>.xlsx`
- [ ] `condosys collect --competencia 09/2026 [--condominio X]`
- [ ] Agrupar condomínios por certificado: um login por certificado (cada login no iHub debita saldo — ADR-007)

## Fase 5 — Enriquecimento por CNPJ

- [ ] Consultar API pública (ex.: BrasilAPI): Simples Nacional, MEI, CNAE do prestador
- [ ] Cache local em SQLite

## Fase 6 — Pré-análise de retenções

- [ ] Regras por código de serviço (LC 116) mantidas pela equipe (arquivo editável)
- [ ] Alertas (`Flag`), por exemplo:
  - "IRRF destacado — condomínio não retém IRRF"
  - "possível retenção de INSS 11%"
  - "PIS/COFINS não somados à CSLL — verificar NT 07"
  - "nota de venda com indício de serviço"
- [ ] Sugestões apenas de referência: 4,65% (PIS/COFINS/CSLL) e base do INSS (retido ÷ 0,11)
- **O sistema sinaliza; o funcionário decide.**

## Fase 7 — Conferência com as planilhas de controle

- [ ] Ler "Controle de PIS", "Controle de INSS" e controle de ISSQN (Google Sheets)
- [ ] Marcar cada nota como "nova" ou "já lançada"

## Fase 8 — Interface para o funcionário

- [ ] Janela mínima: competência, condomínios, botão Executar, barra de progresso, abrir o Excel
- [ ] Executável Windows com **PyInstaller** (incluir navegador ou usar Edge do sistema)

## Fase 9 (futuro) — e-CAC / DARF

- [ ] Avaliar viabilidade (gov.br + captcha); provavelmente semi-automatizado
