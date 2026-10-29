// condosys page logic. Talks to the local Python API; no Node access (see preload.js).
"use strict";

const MONTHS = [
  "janeiro", "fevereiro", "março", "abril", "maio", "junho",
  "julho", "agosto", "setembro", "outubro", "novembro", "dezembro",
];
const STATE_LABEL = {
  ok: "Válido",
  vence: "Vence em breve",
  vencido: "Vencido",
  "sem-senha": "Senha não cadastrada",
  erro: "Com problema",
};

let api = null;
let health = null;
let competence = previousMonth(new Date());
let condominiums = [];
let lastResults = new Map(); // cnpj formatted -> summary
let lastOutput = null;
let pollTimer = null;

// --- helpers ---------------------------------------------------------------------------

function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs)) {
    if (value === undefined || value === null || value === false) continue;
    if (key === "class") node.className = value;
    else if (key.startsWith("on")) node.addEventListener(key.slice(2), value);
    else if (value === true) node.setAttribute(key, "");
    else node.setAttribute(key, value);
  }
  for (const child of children.flat()) {
    if (child === null || child === undefined || child === false) continue;
    node.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return node;
}

function previousMonth(date) {
  const month = date.getMonth(); // 0-based: previous month of the current one
  return month === 0
    ? { month: 12, year: date.getFullYear() - 1 }
    : { month, year: date.getFullYear() };
}

function competenceText(c) {
  return `${String(c.month).padStart(2, "0")}/${c.year}`;
}

const brl = new Intl.NumberFormat("pt-BR", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
function money(value) {
  return value === undefined || value === null ? "" : brl.format(Number(value));
}

function formatDate(iso) {
  if (!iso) return "";
  const [y, m, d] = iso.slice(0, 10).split("-");
  return `${d}/${m}/${y}`;
}

function banner(message, kind = "error") {
  const box = document.getElementById("banner");
  if (!message) {
    box.hidden = true;
    return;
  }
  box.textContent = message;
  box.className = kind === "info" ? "banner info" : "banner";
  box.hidden = false;
}

async function call(method, path, body) {
  if (!api) throw new Error("O condosys ainda está iniciando.");
  const response = await fetch(`http://127.0.0.1:${api.port}${path}`, {
    method,
    headers: { "X-Condosys-Token": api.token, "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    const detail = typeof data.detail === "string" ? data.detail : `HTTP ${response.status}`;
    throw new Error(detail);
  }
  return data;
}

function stateMark(state, detail) {
  return el(
    "span",
    {},
    el("span", { class: `state ${state}` }, STATE_LABEL[state] || state),
    detail ? el("span", { class: "detail" }, detail) : null,
  );
}

function emptyRow(columns, text) {
  return el("tr", { class: "empty" }, el("td", { colspan: columns }, text));
}

// --- navigation --------------------------------------------------------------------------

const loaders = {
  coleta: loadCollect,
  condominios: loadCondominiums,
  certificados: loadCertificates,
  planilhas: loadOutputs,
};

function show(view) {
  for (const button of document.querySelectorAll(".nav-item")) {
    if (button.dataset.view === view) button.setAttribute("aria-current", "page");
    else button.removeAttribute("aria-current");
  }
  for (const section of document.querySelectorAll(".view")) {
    section.hidden = section.id !== `view-${view}`;
  }
  banner(null);
  return loaders[view]().catch((err) => banner(err.message));
}
window.__condosysShow = show;

for (const button of document.querySelectorAll(".nav-item")) {
  button.addEventListener("click", () => show(button.dataset.view));
}

// --- Coleta do mês -----------------------------------------------------------------------

function renderMonth() {
  const label = document.getElementById("month-label");
  label.replaceChildren(
    MONTHS[competence.month - 1].replace(/^./, (c) => c.toUpperCase()),
    el("small", {}, String(competence.year)),
  );
  document.getElementById("run-collect").textContent =
    `Coletar notas de ${MONTHS[competence.month - 1]} de ${competence.year}`;
}

function shiftMonth(delta) {
  let month = competence.month + delta;
  let year = competence.year;
  if (month < 1) { month = 12; year -= 1; }
  if (month > 12) { month = 1; year += 1; }
  competence = { month, year };
  lastResults = new Map();
  document.getElementById("result").hidden = true;
  renderMonth();
  renderCollectTable();
}

function selectedCnpjs() {
  return [...document.querySelectorAll("#collect-table tbody input[type=checkbox]:checked")]
    .map((box) => box.value);
}

function renderCollectTable() {
  const body = document.querySelector("#collect-table tbody");
  const active = condominiums.filter((c) => c.active);
  if (!active.length) {
    body.replaceChildren(emptyRow(9,
      "Nenhum condomínio ativo. Cadastre os certificados e use \"Atualizar a partir dos certificados\" em Condomínios."));
    return;
  }
  body.replaceChildren(...active.map((c) => {
    const result = lastResults.get(c.cnpj_formatted);
    const ready = c.certificate_state === "ok" || c.certificate_state === "vence";
    let status = ready
      ? el("span", { class: "muted" }, "Pronto para coletar")
      : el("span", { class: "detail" }, c.certificate_message || STATE_LABEL[c.certificate_state]);
    if (result) {
      status = result.success
        ? el("span", { class: "state ok" }, "Coletado")
        : stateMark("erro", result.error);
    }
    return el("tr", {},
      el("td", {}, el("input", {
        type: "checkbox", value: c.cnpj, checked: ready, disabled: !ready,
        "aria-label": `Incluir ${c.name}`,
      })),
      el("td", {}, c.name),
      el("td", { class: "muted nowrap" }, c.cnpj_formatted),
      el("td", {}, stateMark(c.certificate_state)),
      el("td", { class: "num" }, result ? result.invoices : ""),
      el("td", { class: "num" }, result ? money(result.amount) : ""),
      el("td", { class: "num" }, result ? money(result.inss) : ""),
      el("td", { class: "num" }, result ? money(result.csrf) : ""),
      el("td", {}, status),
    );
  }));
}

async function loadCollect() {
  renderMonth();
  condominiums = await call("GET", "/api/condominiums");
  renderCollectTable();
}

async function runCollect() {
  const cnpjs = selectedCnpjs();
  if (!cnpjs.length) {
    banner("Selecione ao menos um condomínio com certificado válido.");
    return;
  }
  banner(null);
  document.getElementById("result").hidden = true;
  document.getElementById("run-collect").disabled = true;
  const job = await call("POST", "/api/jobs/collect", {
    competence: competenceText(competence),
    cnpjs,
    sync: !document.getElementById("only-local").checked,
  }).catch((err) => {
    document.getElementById("run-collect").disabled = false;
    banner(err.message);
    return null;
  });
  if (job) watchJob(job.id);
}

function renderJob(job) {
  const progress = document.getElementById("progress");
  progress.hidden = job.status !== "running";
  const done = job.status === "running" ? Math.max(job.current - 1, 0) : job.total;
  document.getElementById("progress-fill").style.width = `${(done / Math.max(job.total, 1)) * 100}%`;
  document.getElementById("progress-text").textContent = job.log.at(-1) || "Iniciando…";

  const logBox = document.getElementById("log-box");
  logBox.hidden = job.log.length === 0;
  document.getElementById("log").replaceChildren(...job.log.map((line) => el("li", {}, line)));

  lastResults = new Map(job.results.map((r) => [r.cnpj, r]));
  renderCollectTable();
}

function watchJob(id) {
  clearInterval(pollTimer);
  pollTimer = setInterval(async () => {
    let job;
    try {
      job = await call("GET", `/api/jobs/${id}`);
    } catch (err) {
      clearInterval(pollTimer);
      banner(err.message);
      document.getElementById("run-collect").disabled = false;
      return;
    }
    renderJob(job);
    if (job.status === "running") return;
    clearInterval(pollTimer);
    document.getElementById("run-collect").disabled = false;
    if (job.status === "error") {
      banner(`A coleta parou: ${job.error}`);
      return;
    }
    const failed = job.results.filter((r) => !r.success).length;
    const notes = job.results.reduce((sum, r) => sum + r.invoices, 0);
    lastOutput = job.output_file;
    document.getElementById("result-text").textContent =
      `${notes} notas em ${job.results.length - failed} condomínios` +
      (failed ? `; ${failed} com erro (veja a aba Erros da planilha).` : ".");
    document.getElementById("result").hidden = false;
  }, 700);
}

document.getElementById("prev-month").addEventListener("click", () => shiftMonth(-1));
document.getElementById("next-month").addEventListener("click", () => shiftMonth(1));
document.getElementById("run-collect").addEventListener("click", runCollect);
document.getElementById("select-all").addEventListener("change", (event) => {
  for (const box of document.querySelectorAll("#collect-table tbody input[type=checkbox]")) {
    if (!box.disabled) box.checked = event.target.checked;
  }
});
document.getElementById("open-result").addEventListener("click", async () => {
  const error = await window.condosys.openFile(lastOutput);
  if (error) banner(error);
});
document.getElementById("show-result").addEventListener("click", () => window.condosys.showInFolder(lastOutput));

// --- Condomínios -------------------------------------------------------------------------

async function patchCondominium(cnpj, changes) {
  try {
    await call("PATCH", `/api/condominiums/${cnpj}`, changes);
  } catch (err) {
    banner(err.message);
  }
}

async function loadCondominiums() {
  condominiums = await call("GET", "/api/condominiums");
  const body = document.querySelector("#condominium-table tbody");
  if (!condominiums.length) {
    body.replaceChildren(emptyRow(5, "Nenhum condomínio ainda. Cadastre os certificados e clique em \"Atualizar a partir dos certificados\"."));
    return;
  }
  body.replaceChildren(...condominiums.map((c) => el("tr", {},
    el("td", {}, el("input", {
      type: "checkbox", checked: c.active, "aria-label": `${c.name} ativo`,
      onchange: (event) => patchCondominium(c.cnpj, { active: event.target.checked }),
    })),
    el("td", {}, c.name),
    el("td", { class: "muted nowrap" }, c.cnpj_formatted),
    el("td", {}, c.certificate, el("br"), stateMark(c.certificate_state, c.certificate_message)),
    el("td", {}, el("input", {
      type: "text", value: c.notes, placeholder: "Adicionar observação", "aria-label": `Observações de ${c.name}`,
      onchange: (event) => patchCondominium(c.cnpj, { notes: event.target.value }),
    })),
  )));
}

document.getElementById("sync-condominiums").addEventListener("click", async () => {
  try {
    const summary = await call("POST", "/api/condominiums/sync");
    const parts = [];
    if (summary.added.length) parts.push(`Incluídos: ${summary.added.join(", ")}.`);
    if (summary.updated.length) parts.push(`Certificado atualizado: ${summary.updated.join(", ")}.`);
    if (summary.skipped.length) parts.push(`Sem senha cadastrada: ${summary.skipped.join(", ")}.`);
    banner(parts.join("\n") || "Nenhum condomínio novo nos certificados.", "info");
    await loadCondominiums();
  } catch (err) {
    banner(err.message);
  }
});

// --- Certificados ------------------------------------------------------------------------

function askPassword(fileLabel, submit) {
  const dialog = document.getElementById("password-dialog");
  const input = document.getElementById("password-input");
  const error = document.getElementById("password-error");
  document.getElementById("password-file").textContent = fileLabel;
  input.value = "";
  error.hidden = true;
  dialog.showModal();

  const form = document.getElementById("password-form");
  const onSubmit = async (event) => {
    if (event.submitter && event.submitter.value === "cancel") {
      cleanup();
      return;
    }
    event.preventDefault();
    try {
      await submit(input.value);
      cleanup();
      dialog.close();
    } catch (err) {
      error.textContent = err.message;
      error.hidden = false;
      input.select();
    }
  };
  const cleanup = () => {
    form.removeEventListener("submit", onSubmit);
    input.value = "";
  };
  form.addEventListener("submit", onSubmit);
}

function registerPassword(path, label) {
  askPassword(label, async (password) => {
    const added = await call("POST", "/api/certificates", { path, password });
    banner(`Certificado de ${added.holder_name} cadastrado.`, "info");
    await loadCertificates();
  });
}

async function loadCertificates() {
  if (!health) health = await call("GET", "/api/health");
  const certificates = await call("GET", "/api/certificates");
  const body = document.querySelector("#certificate-table tbody");
  if (!certificates.length) {
    body.replaceChildren(emptyRow(6, "Nenhum certificado. Clique em \"Adicionar certificado\" e escolha o arquivo .pfx do condomínio."));
    return;
  }
  const separator = health.certs_dir.includes("\\") ? "\\" : "/";
  body.replaceChildren(...certificates.map((c) => {
    let detail = null;
    if (c.days_to_expire !== null && c.days_to_expire >= 0) detail = `${c.days_to_expire} dias restantes`;
    if (c.error) detail = c.error;
    const action = c.has_password
      ? null
      : el("button", {
          onclick: () => registerPassword(`${health.certs_dir}${separator}${c.file_name}`, c.file_name),
        }, "Cadastrar senha");
    return el("tr", {},
      el("td", {}, c.file_name),
      el("td", {}, c.holder_name || ""),
      el("td", { class: "muted nowrap" }, c.cnpj || ""),
      el("td", { class: "nowrap" }, formatDate(c.not_after)),
      el("td", {}, stateMark(c.state, detail)),
      el("td", {}, action),
    );
  }));
}

document.getElementById("add-certificate").addEventListener("click", async () => {
  const path = await window.condosys.pickCertificate();
  if (path) registerPassword(path, path.split(/[\\/]/).pop());
});

// --- Planilhas ---------------------------------------------------------------------------

async function loadOutputs() {
  const files = await call("GET", "/api/outputs");
  const body = document.querySelector("#output-table tbody");
  if (!files.length) {
    body.replaceChildren(emptyRow(3, "Nenhuma planilha ainda. Rode uma coleta em \"Coleta do mês\"."));
    return;
  }
  body.replaceChildren(...files.map((f) => el("tr", {},
    el("td", {}, f.name),
    el("td", { class: "muted" }, f.modified.replace("T", " ")),
    el("td", { class: "num" },
      el("button", { onclick: () => window.condosys.openFile(f.path) }, "Abrir"), " ",
      el("button", { onclick: () => window.condosys.showInFolder(f.path) }, "Mostrar na pasta"),
    ),
  )));
}

// --- start-up ----------------------------------------------------------------------------

function connected(info) {
  if (api) return;
  api = info;
  document.getElementById("connection").textContent = "Conectado";
  show("coleta");
}

renderMonth();
window.condosys.onApiReady(connected);
window.condosys.onApiFailed((message) => {
  document.getElementById("connection").textContent = "Sem conexão";
  banner(`Não foi possível iniciar o condosys.\n${message}`);
});
window.condosys.apiInfo().then((info) => info && connected(info));
