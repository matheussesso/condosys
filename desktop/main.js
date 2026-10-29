// Electron main process: starts the Python backend (condosys serve), opens the window and
// offers the few OS services the page needs (file dialog, open file, show in folder).
const { app, BrowserWindow, dialog, ipcMain, shell } = require("electron");
const { spawn, execFile } = require("node:child_process");
const crypto = require("node:crypto");
const fs = require("node:fs");
const path = require("node:path");
const readline = require("node:readline");

const PROJECT_DIR = path.resolve(__dirname, "..");
const READY_TIMEOUT_MS = 60_000;

let backend = null;
let api = null; // { port, token }
let mainWindow = null;
let baseDir = null; // project folder reported by the backend

function backendCommand() {
  // Packaged app (phase 9): resources/backend/condosys-backend(.exe).
  const exe = process.platform === "win32" ? "condosys-backend.exe" : "condosys-backend";
  const bundled = path.join(process.resourcesPath || "", "backend", exe);
  if (app.isPackaged && fs.existsSync(bundled)) {
    return { command: bundled, args: ["serve", "--port", "0"], cwd: path.dirname(bundled) };
  }
  // Development: the Python project next to this folder, through uv.
  const custom = process.env.CONDOSYS_BACKEND;
  if (custom) {
    return { command: custom, args: ["serve", "--port", "0"], cwd: PROJECT_DIR };
  }
  return { command: "uv", args: ["run", "condosys", "serve", "--port", "0"], cwd: PROJECT_DIR };
}

function startBackend() {
  return new Promise((resolve, reject) => {
    const token = crypto.randomBytes(32).toString("base64url");
    const { command, args, cwd } = backendCommand();
    backend = spawn(command, args, {
      cwd,
      env: { ...process.env, CONDOSYS_API_TOKEN: token, CONDOSYS_EXIT_ON_STDIN_EOF: "1" },
      stdio: ["pipe", "pipe", "pipe"],
      windowsHide: true,
    });
    const stderr = [];
    const timer = setTimeout(
      () => reject(new Error("o backend não respondeu em 60 s")),
      READY_TIMEOUT_MS,
    );
    backend.on("error", (err) => {
      clearTimeout(timer);
      reject(new Error(`não foi possível iniciar "${command}": ${err.message}`));
    });
    backend.on("exit", (code) => {
      clearTimeout(timer);
      if (!api) reject(new Error(`o backend terminou (código ${code}).\n${stderr.join("")}`));
      backend = null;
    });
    backend.stderr.on("data", (chunk) => {
      stderr.push(chunk.toString());
      if (stderr.length > 50) stderr.shift();
    });
    readline.createInterface({ input: backend.stdout }).on("line", (line) => {
      try {
        const message = JSON.parse(line);
        if (message.event === "ready") {
          clearTimeout(timer);
          api = { port: message.port, token };
          resolve(api);
        }
      } catch {
        // not a protocol line
      }
    });
  });
}

function stopBackend() {
  if (!backend) return;
  const pid = backend.pid;
  backend.stdin.end(); // the backend exits when stdin closes
  if (process.platform === "win32") {
    // "uv run" starts python as a child: end the whole tree.
    execFile("taskkill", ["/pid", String(pid), "/T", "/F"], () => {});
  } else {
    backend.kill();
  }
  backend = null;
}

function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1280,
    height: 820,
    minWidth: 980,
    minHeight: 640,
    title: "condosys",
    backgroundColor: "#EEF2EF",
    webPreferences: {
      preload: path.join(__dirname, "preload.js"),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
    },
  });
  mainWindow.removeMenu();
  // Links never open inside the app.
  mainWindow.webContents.setWindowOpenHandler(() => ({ action: "deny" }));
  mainWindow.webContents.on("will-navigate", (event) => event.preventDefault());
  mainWindow.loadFile(path.join(__dirname, "renderer", "index.html"));
  return mainWindow;
}

function isInside(base, target) {
  const relative = path.relative(base, target);
  return relative && !relative.startsWith("..") && !path.isAbsolute(relative);
}

ipcMain.handle("api:info", () => (baseDir ? api : null));

ipcMain.handle("dialog:pick-certificate", async () => {
  const result = await dialog.showOpenDialog(mainWindow, {
    title: "Escolher certificado A1",
    properties: ["openFile"],
    filters: [{ name: "Certificado A1", extensions: ["pfx", "p12"] }],
  });
  return result.canceled ? null : result.filePaths[0];
});

// Only files produced by condosys (inside its project folder) can be opened from the page.
ipcMain.handle("shell:open", async (_event, filePath) => {
  if (!baseDir || !isInside(baseDir, filePath)) return "caminho fora da pasta do condosys";
  return shell.openPath(filePath);
});
ipcMain.handle("shell:show", (_event, filePath) => {
  if (baseDir && isInside(baseDir, filePath)) shell.showItemInFolder(filePath);
});

async function fetchBaseDir() {
  const response = await fetch(`http://127.0.0.1:${api.port}/api/health`, {
    headers: { "X-Condosys-Token": api.token },
  });
  if (!response.ok) throw new Error(`backend respondeu HTTP ${response.status}`);
  baseDir = (await response.json()).base_dir;
}

async function waitForHealth() {
  // The ready line is printed just before the server binds: retry briefly.
  for (let attempt = 0; attempt < 50; attempt += 1) {
    try {
      await fetchBaseDir();
      return;
    } catch {
      await new Promise((r) => setTimeout(r, 200));
    }
  }
  throw new Error("o backend não respondeu ao teste de conexão");
}

async function captureScreenshots(win) {
  // Development aid: `npm run screenshot` saves each screen to debug/ui/ and quits.
  const outDir = path.join(PROJECT_DIR, "debug", "ui");
  fs.mkdirSync(outDir, { recursive: true });
  for (const view of ["coleta", "condominios", "certificados", "planilhas"]) {
    await win.webContents.executeJavaScript(`window.__condosysShow && window.__condosysShow("${view}")`);
    await new Promise((r) => setTimeout(r, 1200));
    const image = await win.webContents.capturePage();
    fs.writeFileSync(path.join(outDir, `${view}.png`), image.toPNG());
  }
  app.quit();
}

app.whenReady().then(async () => {
  const win = createWindow();
  try {
    await startBackend();
    await waitForHealth();
    win.webContents.send("api:ready", api);
  } catch (err) {
    win.webContents.send("api:failed", String(err.message || err));
  }
  if (process.argv.includes("--screenshot")) {
    setTimeout(() => captureScreenshots(win), 2500);
  }
});

app.on("window-all-closed", () => app.quit());
app.on("before-quit", stopBackend);
process.on("exit", stopBackend);
