# Roadmap — condosys

Reformulado em 29/10/2026 (ADR-011): só APIs oficiais, certificado de cada condomínio,
interface Electron. As fases antigas de portal/scraping (1–2) foram encerradas (ADR-010).

## Concluído

- [x] **Fundação** — projeto uv/Python 3.12, CLI, settings, logging, modelos, CNPJ (inclusive alfanumérico), certificados A1 + keyring, testes
- [x] **ADN** — consulta por NSU com mTLS, sincronização incremental, armazenamento local, leitura do XML nacional (validada com notas reais), notas tomadas por competência
- [x] **Reformulação** — remoção do scraping; planilha de condomínios sem `modo_acesso`; `config sync` a partir de `certs/`
- [x] **Coleta em lote + Excel** — `condosys coletar -c MM/AAAA`: um condomínio por vez; abas Notas, Resumo, Erros, Controle PIS, Controle INSS, Controle ISSQN, Sobre
- [x] **API local** — `condosys serve` (FastAPI, 127.0.0.1, token por sessão)
- [x] **Interface Electron (1ª versão)** — certificados, condomínios, coleta com progresso, planilhas geradas

## Próximas fases

### Fase 5 — Pré-análise de retenções
- [ ] Enriquecimento do prestador (Simples Nacional, MEI, CNAE) com cache local
- [ ] Regras por código de serviço (LC 116 / cTribNac) mantidas pela equipe
- [ ] Alertas: IRRF destacado (condomínio não retém), INSS 11% possível, PIS/COFINS fora da CSLL (NT 07), nota de venda com indício de serviço
- [ ] Revisão na interface: aprovar / ajustar / rejeitar cada retenção (o sistema sinaliza, o funcionário decide)

### Fase 6 — Google Sheets
- [ ] Conta de serviço Google + compartilhamento das planilhas Controle de PIS / INSS / ISSQN
- [ ] Mapear aba de cada condomínio; lançar só notas aprovadas; marcar "já lançada" (sem duplicar)

### Fase 7 — EFD-Reinf (webservice oficial, certificado do condomínio)
- [ ] Gerar e assinar R-2010 (INSS retido) e R-4020 (PIS/COFINS/CSLL/IRRF)
- [ ] Fechamento R-2099 / R-4099; consulta de recibos e erros
- [ ] Tudo primeiro em **produção restrita**; transmissão real só com confirmação na interface

### Fase 8 — DCTFWeb e DARF (Integra Contador — Serpro)
- [ ] Contrato na Loja Serpro (pendente do escritório) e credenciais
- [ ] Autorização de procurador / termo de autorização com o certificado do condomínio
- [ ] Consultar e transmitir a DCTFWeb gerada pela Reinf; emitir o DARF; guardar recibos e PDFs
- [ ] Confirmação explícita antes de cada transmissão

### Fase 9 — Distribuição Windows
- [ ] Backend empacotado com PyInstaller (`condosys-backend.exe`)
- [ ] Instalador com electron-builder (NSIS), atualização e ícone
- [ ] Pasta de dados por usuário (`%APPDATA%\condosys`) em vez da pasta do projeto

### Pendências do ADN
- [ ] Eventos de cancelamento/substituição (`/NFSe/{ChaveAcesso}/Eventos`)
- [ ] Confirmar no leiaute nacional `tpRetISSQN`, `cStat` e a regra da NT 07
