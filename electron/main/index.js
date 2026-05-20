const { app, BrowserWindow, ipcMain, shell } = require("electron");
const { spawn } = require("child_process");
const path = require("path");
const fs   = require("fs");

let mainWindow;
let backendProcess;

const isDev = process.env.NODE_ENV === "development" || !app.isPackaged;
const BACKEND_PORT = 8000;

function startBackend() {
  const backendDir = path.join(__dirname, "../../backend");
  const candidates = process.platform === "win32"
    ? ["py", "python", "python3"]
    : ["python3", "python"];

  for (const cmd of candidates) {
    try {
      backendProcess = spawn(cmd, ["-m", "uvicorn", "main:app", "--host", "127.0.0.1", "--port", String(BACKEND_PORT)], {
        cwd: backendDir,
        env: { ...process.env },
        stdio: ["ignore", "pipe", "pipe"],
      });
      backendProcess.stdout?.on("data", d => console.log("[backend]", d.toString().trim()));
      backendProcess.stderr?.on("data", d => console.error("[backend]", d.toString().trim()));
      backendProcess.on("exit", code => console.log(`[backend] exited with code ${code}`));
      console.log(`[main] Backend started with '${cmd}' (PID ${backendProcess.pid})`);
      return;
    } catch (e) {
      console.warn(`[main] '${cmd}' not found, trying next…`);
    }
  }
  console.error("[main] Could not start backend: Python not found");
}

function stopBackend() {
  if (backendProcess) {
    backendProcess.kill();
    backendProcess = null;
  }
}

async function createWindow() {
  mainWindow = new BrowserWindow({
    width:  1280, height: 820, minWidth: 900, minHeight: 600,
    titleBarStyle: "hiddenInset",
    backgroundColor: "#0a0a0a",
    webPreferences: {
      preload: path.join(__dirname, "../preload/index.js"),
      contextIsolation: true,
      nodeIntegration:  false,
      webSecurity: !isDev,
    },
    show: false,
  });

  mainWindow.once("ready-to-show", () => {
    mainWindow.show();
    if (isDev) mainWindow.webContents.openDevTools({ mode: "detach" });
  });

  // ── EXTERNAL LINK HANDLING ─────────────────────────────────────────────────
  // Open ALL external URLs (http/https outside our app) in the system browser.
  // Prevents the Electron window from navigating away from the app.

  mainWindow.webContents.setWindowOpenHandler(({ url }) => {
    shell.openExternal(url);
    return { action: "deny" };
  });

  mainWindow.webContents.on("will-navigate", (event, url) => {
    const isAppUrl = url.startsWith("http://localhost:5173") || url.startsWith("file://");
    if (!isAppUrl) {
      event.preventDefault();
      shell.openExternal(url);
    }
  });

  if (isDev) {
    await new Promise(r => setTimeout(r, 1500));
    await mainWindow.loadURL("http://localhost:5173");
  } else {
    await mainWindow.loadFile(path.join(__dirname, "../../dist/renderer/index.html"));
  }

  mainWindow.on("closed", () => { mainWindow = null; });
}

ipcMain.handle("get-credentials", async () => {
  try {
    const envPath = path.join(__dirname, "../../backend/.env");
    if (!fs.existsSync(envPath)) return {};
    const env = fs.readFileSync(envPath, "utf8");
    const parsed = {};
    for (const line of env.split("\n")) {
      const match = line.match(/^([A-Z_]+)=(.*)$/);
      if (match) parsed[match[1].toLowerCase()] = match[2].trim().replace(/^["']|["']$/g, "");
    }
    return {
      aws_access_key_id:     parsed.aws_access_key_id     || "",
      aws_secret_access_key: parsed.aws_secret_access_key || "",
      aws_session_token:     parsed.aws_session_token     || "",
      aws_region:            parsed.aws_region            || "us-east-1",
    };
  } catch { return {}; }
});

ipcMain.handle("open-external", (_, url) => shell.openExternal(url));

app.whenReady().then(async () => {
  startBackend();
  await new Promise(r => setTimeout(r, 2000));
  await createWindow();
});

app.on("window-all-closed", () => {
  stopBackend();
  if (process.platform !== "darwin") app.quit();
});

app.on("activate", () => { if (mainWindow === null) createWindow(); });
app.on("before-quit", stopBackend);
