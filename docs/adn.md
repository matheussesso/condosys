# ADN — Ambiente de Dados Nacional da NFS-e

Fonte oficial para condomínios com **acesso DIRETO** (certificado com a mesma raiz de CNPJ
do condomínio). Procuração não é aceita (ADR-009). Código: `src/condosys/adn.py`;
comando de teste: `condosys adn-test`.

## Primeiro teste real — 23/10/2026

`uv run condosys adn-test --cert sema.pfx` (consulta o CNPJ da própria Sema, NSU 0):

- `GET https://adn.nfse.gov.br/contribuintes/DFe/0?lote=true` com mTLS → **HTTP 200**.
- Resposta JSON: `StatusProcessamento` (`DOCUMENTOS_LOCALIZADOS`), `LoteDFe`, `Alertas`,
  `Erros`, `TipoAmbiente` (`PRODUCAO`), `VersaoAplicativo`, `DataHoraProcessamento`.
- `LoteDFe`: **50 itens** (lote máximo), NSU 1 a 50. Cada item: `NSU`, `ChaveAcesso`
  (50 dígitos, começa com o código do município), `TipoDocumento` (`NFSE`),
  `DataHoraGeracao`, `ArquivoXml` (base64 + gzip).
- XML: raiz `NFSe`, namespace `http://www.sped.fazenda.gov.br/nfse`, `versao="1.00"`.
- **Notas do DF estão lá:** `cLocEmi` e `cLocPrestacao` = `5300108` (Brasília) em todas.
- A Sema aparece como **tomadora** nas 50; emissões de 09/2023 a 12/2025 (o lote começa
  pelo NSU mais antigo — é preciso paginar até o fim para chegar às notas recentes).

## Sincronização e uso (implementado)

- `adn.sync_documents`: chama `GET /contribuintes/DFe/{NSU}?lote=true` a partir do último
  NSU guardado, uma consulta por vez, com pausa (`CONDOSYS_ADN_PAUSE_MS`, padrão 1 s), até
  vir menos de 50 itens, outro `StatusProcessamento` ou HTTP 404; no máximo
  `CONDOSYS_ADN_MAX_BATCHES` lotes por execução (a próxima continua). NSUs repetidos são
  ignorados.
- Armazenamento local em `data/adn/<CNPJ>/` (fora do git): `<NSU>_<TIPO>.xml` (XML como
  veio), `<NSU>_<TIPO>.key` (chave de acesso) e `state.json` (`last_nsu`).
- `nfse_nacional.parse_nfse_xml`: XML → `InvoiceDetail` (validado com as 50 notas reais).
- `services.adn_invoices.taken_invoices`: notas em que o CNPJ é **tomador**, com **data
  de emissão** dentro da competência (como na rotina manual); eventos são ignorados.
- Comando: `condosys adn-notas <condomínio> -c 09/2026` (ou `--cert sema.pfx`);
  `--sem-sincronizar` usa só o que já foi baixado.
- Pendente: cancelamentos/substituições (eventos, `/NFSe/{ChaveAcesso}/Eventos`) — tratar
  ao encontrar um caso real.

## Campos encontrados → modelo `InvoiceDetail`

Caminhos relativos a `/NFSe/infNFSe`. "n/50" = em quantas das 50 notas o campo apareceu
(campo ausente = zero/não informado).

| campo do modelo | XML | ocorrência |
|---|---|---|
| `number` | `nNFSe` | 50/50 |
| `issue_date` | `DPS/infDPS/dhEmi` | 50/50 |
| (competência) | `DPS/infDPS/dCompet` | 50/50 |
| `amount` | `DPS/infDPS/valores/vServPrest/vServ` | 50/50 |
| `iss_amount` | `valores/vISSQN` | 23/50 |
| `tax_withheld` / `iss_withheld` | `DPS/infDPS/valores/trib/tribMun/tpRetISSQN` — o condosys considera `2` (tomador) e `3` (intermediário) como retido; `1` em todas as 50 notas; confirmar no leiaute nacional | 50/50 |
| `provider_document` | `emit/CNPJ` (e `DPS/infDPS/prest/CNPJ`) | 50/50 |
| `provider_name` | `emit/xNome` | 50/50 |
| `taker_document` | `DPS/infDPS/toma/CNPJ` | 50/50 |
| `taker_name` | `DPS/infDPS/toma/xNome` | 50/50 |
| `status` | `cStat` | 50/50 |
| `version` | atributo `versao` da raiz | 50/50 |
| `service_code` | `DPS/infDPS/serv/cServ/cTribNac` (código nacional, 6 dígitos, ex. `990101`) | 50/50 |
| — | `DPS/infDPS/serv/cServ/cNBS` | 9/50 |
| `service_description` | `DPS/infDPS/serv/cServ/xDescServ` | 50/50 |
| `service_location` | `DPS/infDPS/serv/locPrest/cLocPrestacao` (IBGE) + `xLocPrestacao` | 50/50 |
| `pis` / `cofins` | `DPS/infDPS/valores/trib/tribFed/piscofins/vPis`, `vCofins` | 10/50 |
| `csll` | `DPS/infDPS/valores/trib/tribFed/vRetCSLL` | 10/50 |
| `inss` | `DPS/infDPS/valores/trib/tribFed/vRetCP` | 10/50 |
| `irrf` | `DPS/infDPS/valores/trib/tribFed/vRetIRRF` | 10/50 |
| `social_contributions_withheld` | a confirmar: `vTotalRet` (27/50) inclui as federais retidas? (NT 07) | — |
| `net_amount` | `valores/vLiq` | 50/50 |
| — | regime do prestador: `DPS/infDPS/prest/regTrib/opSimpNac`, `regEspTrib` | 50/50 |

Pendências para a Fase 3: confirmar no leiaute nacional da NFS-e o significado de
`cStat`, `tpRetISSQN`, `tribISSQN`, `opSimpNac`; como a NT 07 aparece (PIS/COFINS
somados à CSLL); onde ficam as deduções; e o mapeamento `cTribNac` → item da LC 116
(usado na pré-análise da Fase 6).

## Cuidados

- Os XML em `debug/adn/` têm dados fiscais reais (fora do git). Para fixtures de teste,
  anonimizar nomes e CNPJs de terceiros.
- Uma consulta por vez; respeitar a paginação, sem rajadas.
