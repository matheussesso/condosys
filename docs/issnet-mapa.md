# Mapa do ISSNet On-Line (DF)

Mapa das telas e seletores do portal. **Preencher a partir do material do recon**
(`debug/recon/<timestamp>/`), nunca de memória. Cada seletor confirmado aqui deve ir para
`src/condosys/portals/issnet/selectors.py`.

Legenda: ✅ confirmado no recon · 🟡 provisório (texto da rotina) · ❌ a capturar

## Como capturar

1. `uv run condosys recon "<condomínio>"` — faz o login e abre o Playwright Inspector.
2. Navegue manualmente pelas telas abaixo. Cada página carregada é salva automaticamente
   em `debug/recon/<timestamp>/` (`NNN_<slug>.html`, `NNN_<slug>.png`, HTML de cada
   frame) e todas as requisições ficam em `requests.log`.
3. No Inspector, use **Pick locator** para obter o seletor do elemento e anote aqui.
4. Prefira `id` estáveis (ASP.NET: `ctl00_ContentPlaceHolder1_...`) ou papel + nome
   acessível; evite XPath posicional.
5. Copie para `tests/fixtures/` os HTML que servirão de teste (grade com e sem resultados,
   grade com mais de uma página, nota aberta, XML se houver).

## 1. Login — `Login/Login.aspx`

URL: `https://iss.fazenda.df.gov.br/online/Login/Login.aspx?ReturnUrl=%2fonline`
(verificado em 22/10/2026 na página pública, sem certificado — ver ADR-007).

| elemento | seletor | status |
|---|---|---|
| botão "Logar com certificado digital" | `#btnAcionaCertificado` (`onclick="btnAssinar_onClick()"`) | ✅ |
| licença do iHub (não logar) | `#licencaCertificado` (hidden) | ✅ |
| ticket devolvido pelo popup | `#ticketcertificado` (hidden), enviado por `__doPostBack('btnToken')` | ✅ |
| popup de autenticação | `https://api.ihub.com.br/auth?token=...` — pede o certificado no TLS | ✅ |
| erros do iHub | `alert()` na página de login | ✅ |
| login por usuário/senha (não usado) | `#txtLogin`, `#txtSenha`, `#btnAcessar` | ✅ |
| URL/elemento que indica login concluído | | ❌ |
| mensagem de erro do portal (fora do alert) | | ❌ |

Observações: com o navegador invisível (headless) o Cloudflare bloqueia os scripts de
`www.notacontrol.com.br` e o botão não funciona; use sempre a janela visível.

## 1.1 Seleção de empresa (procuração) — `default/empresas.aspx`

Vista em 23/10/2026 (print do login manual no Firefox com o certificado da Sema). Após o
login por procuração, o portal vai direto para esta tela (URL
`https://iss.fazenda.df.gov.br/online/default/empresas.aspx?<parâmetro cifrado>`).
Seletores ainda não capturados — só o que aparece na tela:

| elemento | observação | status |
|---|---|---|
| título "Empresas" / "Selecione a Empresa" | | 🟡 texto |
| filtro Inscrição Municipal | campo texto | ❌ |
| filtro CPF / CNPJ | campo texto — usar para achar o condomínio | ❌ |
| filtro Nome / Razão Social | campo texto | ❌ |
| Mês / Ano | selects (ex.: "Setembro" / "2026") — **competência escolhida aqui** | ❌ |
| botão Localizar | ícone de lupa | ❌ |
| grade | colunas: Nome / Razão Social, CPF/CNPJ (formatado), Insc. Municipal, Status, Recadastrado, Denominação, Selecione | ❌ |
| botão Selecione (✓ verde) por linha | entra no ambiente do condomínio | ❌ |
| paginação | links "1 2 3 4" (10 linhas por página) | ❌ |
| cabeçalho | nome do certificado ("Sema Contabilidade e..."), "Sair", "Acessado em: dd/mm/aaaa hh:mm:ss" | ❌ |

Consequências: a seleção do contribuinte da procuração é uma **tela própria** (não um
seletor no cabeçalho); a competência provavelmente já é definida aqui. Filtrar por CNPJ +
Localizar + Selecione deve bastar para automatizar (Fase 1/2, após o recon).

## 2. Cabeçalho (após login)

| elemento | seletor | status |
|---|---|---|
| nome/CNPJ do contribuinte atual | | ❌ |
| competência atual | | ❌ |
| seletor de contribuinte (procuração) | | ❌ |
| sair / logout | | ❌ |

## 3. Menu → Declaração de Serviços Contratados → Consulta de Notas Tomadas

| elemento | seletor | status |
|---|---|---|
| "Menu" | `get_by_text("Menu")` | 🟡 |
| "Declaração de Serviços Contratados" | | 🟡 texto |
| "Consulta de Notas Tomadas" | | 🟡 texto |
| URL direta da tela (se estável) | | ❌ |

## 4. Consulta Notas Tomadas — filtros

| elemento | seletor | status |
|---|---|---|
| Série (opção "Nota Fiscal de Serviço Eletrônica - NFS-e") | | ❌ |
| N.º Inicial / N.º Final | | ❌ |
| "Filtros Adicionais" (▽) | | ❌ |
| Data Emissão Inicial / Final (formato?) | | ❌ |
| CPF/CNPJ do Prestador | | ❌ |
| Status NFS-e ("Normal"/"Cancelado") | | ❌ |
| Natureza de Operação | | ❌ |
| botão "Localizar" | | ❌ |

## 5. Grade "Documentos Fiscais"

Colunas (rotina): Nº Doc., Valor Nota, Valor Total ISSQN, Data Emissão, Imposto Retido,
CPF/CNPJ, Razão Social Prestador, Status, Versão.

| elemento | seletor | status |
|---|---|---|
| tabela | | ❌ |
| linhas de dados | | ❌ |
| paginação (próxima página / tamanho da página) | | ❌ |
| mensagem "nenhum registro" | | ❌ |
| botão Visualizar (abre popup? nova aba? postback?) | | ❌ |
| ícone de documento (XML? PDF?) | | ❌ |
| botão Imprimir | | ❌ |

## 6. Nota aberta ("Visualizar")

Campos a localizar: código de serviço (LC 116 / Código de Tributação Nacional/Municipal),
descrição, local da prestação, ISSQN (e retido?), PIS, COFINS, CSLL,
"Contribuições Sociais — Retidas" (NT 07), INSS, IRRF, deduções, valor líquido,
tomador (CNPJ/nome).

| campo | seletor | status |
|---|---|---|
| | | ❌ |

## Observações do recon

_(anotar aqui comportamentos do portal: postbacks ASP.NET, iframes, popups, tempo de
sessão, mensagens, limites de paginação, etc.)_
