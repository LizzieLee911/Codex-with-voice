const fs = require("node:fs");
const http = require("node:http");
const path = require("node:path");
const { spawn } = require("node:child_process");
const { app, BrowserWindow, ipcMain, Menu, nativeImage, shell, Tray } = require("electron");
const { codexVersion, defaultPaths, runCommand } = require("./codexRunner");

const paths = defaultPaths();
const trayIconPath = path.join(__dirname, "..", "assets", "tray.png");
let mainWindow = null;
let tray = null;
let voiceProcess = null;
let wlkProcess = null;
let wlkStartedByApp = false;
let isQuitting = false;
let quitAfterCleanup = false;
let state = {
  mode: "stopped",
  status: "Stopped",
  voicePid: null,
  wlk: "unknown",
  workspace: paths.workspaceRoot,
  voiceRoot: paths.voiceRoot,
  detectedLanguage: "Waiting",
  sandboxMode: "danger-full-access",
  newSession: false
};

function send(channel, payload) {
  if (mainWindow && !mainWindow.isDestroyed()) {
    mainWindow.webContents.send(channel, payload);
  }
}

function log(line) {
  const entry = `[${new Date().toLocaleTimeString()}] ${line}`;
  send("log", entry);
}

function processLogLine(prefix, line) {
  const match = line.match(/Detected language:\s*(.+)$/i);
  if (match) {
    setState({ detectedLanguage: match[1].trim() });
  }
  log(`${prefix}: ${line}`);
}

function setState(patch) {
  state = { ...state, ...patch };
  send("state", state);
  updateTray();
}

function createTrayIcon() {
  const icon = nativeImage.createFromPath(trayIconPath);
  if (icon.isEmpty()) {
    console.warn(`Tray icon failed to load: ${trayIconPath}`);
  }
  return icon;
}

function showWindow() {
  if (!mainWindow || mainWindow.isDestroyed()) return;
  if (mainWindow.isMinimized()) mainWindow.restore();
  mainWindow.show();
  mainWindow.focus();
}

async function quitApp() {
  if (quitAfterCleanup) return;
  quitAfterCleanup = true;
  isQuitting = true;
  await stopVoice();
  app.quit();
}

function updateTray() {
  if (!tray) return;
  tray.setToolTip(`Codex Voice: ${state.status}`);
  tray.setContextMenu(Menu.buildFromTemplate([
    { label: "Show", click: showWindow },
    { type: "separator" },
    { label: "Start", enabled: !voiceProcess, click: () => startVoice() },
    { label: "Stop", enabled: Boolean(voiceProcess), click: () => stopVoice() },
    { type: "separator" },
    { label: "Quit", click: quitApp }
  ]));
}

function createWindow() {
  mainWindow = new BrowserWindow({
    width: 760,
    height: 640,
    minWidth: 620,
    minHeight: 520,
    backgroundColor: "#f6f6f6",
    icon: createTrayIcon(),
    title: "Codex Voice Companion",
    webPreferences: {
      preload: path.join(__dirname, "preload.js")
    }
  });
  mainWindow.loadFile(path.join(__dirname, "index.html"));
  mainWindow.on("minimize", (event) => {
    event.preventDefault();
    mainWindow.hide();
    log("Window hidden to tray. Voice listener keeps its current state.");
  });
  mainWindow.on("close", (event) => {
    if (isQuitting) return;
    event.preventDefault();
    mainWindow.hide();
    log("Window hidden to tray. Use tray Quit to exit.");
  });
}

function exists(file) {
  try {
    return fs.existsSync(file);
  } catch {
    return false;
  }
}

function checkWlkHealth(timeoutMs = 2500) {
  return new Promise((resolve) => {
    const req = http.get("http://127.0.0.1:8000/health", { timeout: timeoutMs }, (res) => {
      let body = "";
      res.on("data", (chunk) => {
        body += chunk.toString("utf8");
      });
      res.on("end", () => {
        resolve({ ok: res.statusCode === 200, statusCode: res.statusCode, body });
      });
    });
    req.on("timeout", () => {
      req.destroy();
      resolve({ ok: false, error: "timeout" });
    });
    req.on("error", (error) => {
      resolve({ ok: false, error: error.message });
    });
  });
}

async function waitForWlk() {
  const deadline = Date.now() + 120000;
  while (Date.now() < deadline) {
    const health = await checkWlkHealth(1500);
    if (health.ok) {
      setState({ wlk: "ready" });
      return true;
    }
    await new Promise((resolve) => setTimeout(resolve, 1500));
  }
  return false;
}

async function ensureWlk() {
  const health = await checkWlkHealth();
  if (health.ok) {
    setState({ wlk: "ready" });
    return;
  }

  if (!exists(paths.wlkBin)) {
    throw new Error(`WhisperLiveKit executable not found: ${paths.wlkBin}`);
  }

  log("Starting WhisperLiveKit...");
  setState({ wlk: "starting" });
  wlkProcess = spawn(paths.wlkBin, [
    "serve",
    "--backend", "faster-whisper",
    "--model", "large-v3-turbo",
    "--lan", "auto",
    "--pcm-input",
    "--host", "127.0.0.1",
    "--port", "8000",
    "--warmup-file="
  ], {
    cwd: path.join(paths.voiceRoot, "WhisperLiveKit"),
    windowsHide: true
  });
  wlkStartedByApp = true;
  wireProcessLogs(wlkProcess, "wlk");

  const ready = await waitForWlk();
  if (!ready) {
    throw new Error("WhisperLiveKit did not become ready in time.");
  }
  log("WhisperLiveKit ready.");
}

function wireProcessLogs(child, prefix) {
  child.stdout?.on("data", (chunk) => {
    for (const line of chunk.toString("utf8").split(/\r?\n/).filter(Boolean)) {
      processLogLine(prefix, line);
    }
  });
  child.stderr?.on("data", (chunk) => {
    for (const line of chunk.toString("utf8").split(/\r?\n/).filter(Boolean)) {
      processLogLine(prefix, line);
    }
  });
}

function killProcessTree(child) {
  if (!child || child.killed) return Promise.resolve();
  if (process.platform === "win32" && child.pid) {
    return runCommand("taskkill.exe", ["/PID", String(child.pid), "/T", "/F"], { timeoutMs: 10000 });
  }
  child.kill("SIGTERM");
  return Promise.resolve();
}

async function startVoice() {
  if (voiceProcess) {
    log("Voice listener is already running.");
    return state;
  }
  if (!exists(paths.pythonBin)) {
    throw new Error(`Python executable not found: ${paths.pythonBin}`);
  }
  if (!exists(path.join(paths.voiceRoot, "voice_bridge.py"))) {
    throw new Error(`voice_bridge.py not found under ${paths.voiceRoot}`);
  }

  await ensureWlk();
  const args = [
    "voice_bridge.py",
    "--codex-cwd", state.workspace,
    "--codex-sandbox", state.sandboxMode,
    "--submit-codex",
    "--speak"
  ];
  if (state.newSession) {
    args.push("--codex-new-session");
  }

  log(`Starting listener with sandbox: ${state.sandboxMode}; session: ${state.newSession ? "new" : "resume last"}`);
  voiceProcess = spawn(paths.pythonBin, args, {
    cwd: paths.voiceRoot,
    windowsHide: true
  });
  setState({
    mode: "codex",
    status: "Listening",
    voicePid: voiceProcess.pid,
    detectedLanguage: "Waiting"
  });
  wireProcessLogs(voiceProcess, "voice");
  voiceProcess.on("close", (code) => {
    log(`voice process exited with code ${code}`);
    voiceProcess = null;
    setState({ mode: "stopped", status: "Stopped", voicePid: null });
  });
  return state;
}

async function stopVoice() {
  if (voiceProcess) {
    log("Stopping voice listener...");
    await killProcessTree(voiceProcess);
    voiceProcess = null;
  }
  if (wlkStartedByApp && wlkProcess) {
    log("Stopping WhisperLiveKit...");
    await killProcessTree(wlkProcess);
    wlkProcess = null;
    wlkStartedByApp = false;
  }
  setState({ mode: "stopped", status: "Stopped", voicePid: null, wlk: "unknown" });
  return state;
}

async function getEnvironment() {
  const version = await codexVersion();
  const health = await checkWlkHealth();
  setState({ wlk: health.ok ? "ready" : "not running" });
  return {
    ...state,
    appRoot: paths.appRoot,
    voiceRoot: paths.voiceRoot,
    pythonBin: paths.pythonBin,
    wlkBin: paths.wlkBin,
    hasVoiceRoot: exists(paths.voiceRoot),
    hasPython: exists(paths.pythonBin),
    hasBridge: exists(path.join(paths.voiceRoot, "voice_bridge.py")),
    codex: version,
    wlkHealth: health
  };
}

ipcMain.handle("env", getEnvironment);
ipcMain.handle("start", () => startVoice());
ipcMain.handle("stop", stopVoice);
ipcMain.handle("open-turns", () => shell.openPath(path.join(paths.voiceRoot, ".voice", "turns")));
ipcMain.handle("set-workspace", (_event, workspace) => {
  const resolved = path.resolve(workspace || paths.workspaceRoot);
  setState({ workspace: resolved });
  return state;
});
ipcMain.handle("set-sandbox", (_event, sandboxMode) => {
  const allowed = ["read-only", "workspace-write", "danger-full-access"];
  if (!allowed.includes(sandboxMode)) {
    throw new Error(`Unsupported sandbox mode: ${sandboxMode}`);
  }
  setState({ sandboxMode });
  return state;
});
ipcMain.handle("set-new-session", (_event, newSession) => {
  setState({ newSession: Boolean(newSession) });
  return state;
});

app.whenReady().then(() => {
  createWindow();
  tray = new Tray(createTrayIcon());
  tray.on("click", showWindow);
  updateTray();
});

app.on("before-quit", (event) => {
  if (quitAfterCleanup) return;
  event.preventDefault();
  quitApp();
});

app.on("window-all-closed", () => {
  if (isQuitting && process.platform !== "darwin") app.quit();
});
