const fs = require("node:fs");
const http = require("node:http");
const path = require("node:path");
const { spawn } = require("node:child_process");
const { app, BrowserWindow, ipcMain, Menu, nativeImage, shell, Tray } = require("electron");
const { codexVersion, defaultPaths, runCommand } = require("./codexRunner");

const paths = defaultPaths();
const trayIconPath = path.join(__dirname, "..", "assets", "tray.png");
const appIconPath = path.join(__dirname, "..", "assets", "app-icon.ico");
let mainWindow = null;
let bubbleWindow = null;
let tray = null;
let voiceProcess = null;
let wlkProcess = null;
let trackerProcess = null;
let wlkStartedByApp = false;
let listenerWanted = false;
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
  codexMode: "one-time"
};

function send(channel, payload) {
  if (mainWindow && !mainWindow.isDestroyed()) {
    mainWindow.webContents.send(channel, payload);
  }
  if (bubbleWindow && !bubbleWindow.isDestroyed()) {
    bubbleWindow.webContents.send(channel, payload);
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

function createIcon(iconPath) {
  const icon = nativeImage.createFromPath(iconPath);
  if (icon.isEmpty()) {
    console.warn(`Icon failed to load: ${iconPath}`);
  }
  return icon;
}

function showWindow() {
  if (!mainWindow || mainWindow.isDestroyed()) return;
  if (mainWindow.isMinimized()) mainWindow.restore();
  mainWindow.show();
  mainWindow.focus();
}

function showBubble() {
  if (!bubbleWindow || bubbleWindow.isDestroyed() || bubbleWindow.isVisible()) return;
  bubbleWindow.showInactive();
}

async function quitApp() {
  if (quitAfterCleanup) return;
  quitAfterCleanup = true;
  isQuitting = true;
  await stopVoice();
  await stopWindowTracker();
  app.quit();
}

function updateTray() {
  if (!tray) return;
  tray.setToolTip(`Codex Voice: ${state.status}`);
  tray.setContextMenu(Menu.buildFromTemplate([
    { label: "Show", click: showWindow },
    { type: "separator" },
    { label: "Start", enabled: !listenerWanted, click: () => startVoice() },
    { label: "Stop", enabled: listenerWanted, click: () => stopVoice() },
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
    icon: createIcon(appIconPath),
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

function bubbleContextMenu() {
  Menu.buildFromTemplate([
    { label: "Show Panel", click: showWindow },
    { type: "separator" },
    { label: "Start Listening", enabled: !listenerWanted, click: () => startVoice() },
    { label: "Stop Listening", enabled: listenerWanted, click: () => stopVoice() },
    { type: "separator" },
    { label: "Quit", click: quitApp }
  ]).popup({ window: bubbleWindow });
}

function exists(file) {
  try {
    return fs.existsSync(file);
  } catch {
    return false;
  }
}

function wlkCwd() {
  const sourceRoot = path.join(paths.voiceRoot, "WhisperLiveKit");
  return exists(sourceRoot) ? sourceRoot : paths.voiceRoot;
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

function createBubbleWindow() {
  bubbleWindow = new BrowserWindow({
    width: 56,
    height: 56,
    show: false,
    frame: false,
    transparent: true,
    resizable: false,
    movable: false,
    minimizable: false,
    maximizable: false,
    fullscreenable: false,
    alwaysOnTop: true,
    skipTaskbar: true,
    hasShadow: false,
    backgroundColor: "#00000000",
    icon: createIcon(appIconPath),
    title: "Codex Voice Bubble",
    webPreferences: {
      preload: path.join(__dirname, "preload.js")
    }
  });
  bubbleWindow.setAlwaysOnTop(true, "pop-up-menu");
  bubbleWindow.loadFile(path.join(__dirname, "bubble.html"));
  bubbleWindow.webContents.once("did-finish-load", () => {
    bubbleWindow.webContents.send("state", state);
  });
  bubbleWindow.on("closed", () => {
    bubbleWindow = null;
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
    cwd: wlkCwd(),
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

function trackerScriptPath() {
  const devPath = path.join(__dirname, "window_tracker.py");
  const unpackedPath = path.join(process.resourcesPath || "", "app.asar.unpacked", "src", "window_tracker.py");
  if (devPath.includes(".asar")) return unpackedPath;
  return exists(devPath) ? devPath : unpackedPath;
}

function trackerPythonBin() {
  if (exists(paths.pythonBin)) return paths.pythonBin;
  return process.platform === "win32" ? "python.exe" : "python3";
}

function placeBubble(target) {
  if (!bubbleWindow || bubbleWindow.isDestroyed()) return;
  if (!target || !target.found || target.minimized || target.width < 240 || target.height < 180) {
    bubbleWindow.hide();
    return;
  }

  const size = 56;
  const margin = 18;
  const topOffset = 82;
  const x = Math.max(target.left + margin, target.right - size - margin);
  let y = target.top + topOffset;
  const maxY = target.bottom - size - margin;
  if (y > maxY) y = target.top + margin;

  bubbleWindow.setBounds({
    x: Math.round(x),
    y: Math.round(y),
    width: size,
    height: size
  }, false);
  showBubble();
}

function startWindowTracker() {
  if (process.platform !== "win32" || trackerProcess) return;
  const script = trackerScriptPath();
  if (!exists(script)) {
    log(`Bubble tracker not found: ${script}`);
    return;
  }

  trackerProcess = spawn(trackerPythonBin(), ["-u", script], {
    cwd: paths.appRoot,
    windowsHide: true
  });
  trackerProcess.stdout?.on("data", (chunk) => {
    for (const line of chunk.toString("utf8").split(/\r?\n/).filter(Boolean)) {
      try {
        placeBubble(JSON.parse(line));
      } catch (error) {
        log(`Bubble tracker parse error: ${error.message || error}`);
      }
    }
  });
  trackerProcess.stderr?.on("data", (chunk) => {
    for (const line of chunk.toString("utf8").split(/\r?\n/).filter(Boolean)) {
      log(`bubble-tracker: ${line}`);
    }
  });
  trackerProcess.on("error", (error) => {
    log(`Bubble tracker failed: ${error.message || error}`);
    trackerProcess = null;
  });
  trackerProcess.on("close", (code) => {
    if (!isQuitting && !quitAfterCleanup && code !== 0) {
      log(`Bubble tracker exited with code ${code}`);
    }
    trackerProcess = null;
    if (bubbleWindow && !bubbleWindow.isDestroyed()) bubbleWindow.hide();
  });
}

async function stopWindowTracker() {
  if (!trackerProcess) return;
  await killProcessTree(trackerProcess);
  trackerProcess = null;
}

async function launchVoiceWorker() {
  if (voiceProcess) {
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
    "-u",
    "voice_bridge.py",
    "--codex-cwd", state.workspace,
    "--codex-sandbox", state.sandboxMode,
    "--codex-mode", state.codexMode,
    "--codex-timeout-seconds", "300",
    "--input-gain", "4.0",
    "--submit-codex",
    "--speak",
    "--once"
  ];

  log(`Starting listener turn with sandbox: ${state.sandboxMode}; mode: ${state.codexMode}`);
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
    log(`voice turn exited with code ${code}`);
    voiceProcess = null;
    if (!listenerWanted || isQuitting || quitAfterCleanup) {
      setState({ mode: "stopped", status: "Stopped", voicePid: null });
      return;
    }
    setState({ mode: "codex", status: "Restarting", voicePid: null, detectedLanguage: "Waiting" });
    setTimeout(() => {
      if (!listenerWanted || voiceProcess) return;
      launchVoiceWorker().catch((error) => {
        log(`ERROR: ${error.message || error}`);
        listenerWanted = false;
        setState({ mode: "stopped", status: "Stopped", voicePid: null });
      });
    }, 750);
  });
  return state;
}

async function startVoice() {
  if (listenerWanted) {
    log("Voice listener is already running.");
    return state;
  }
  listenerWanted = true;
  updateTray();
  return launchVoiceWorker();
}

async function stopVoice() {
  listenerWanted = false;
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

async function toggleVoice() {
  return listenerWanted ? stopVoice() : startVoice();
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
ipcMain.handle("toggle", toggleVoice);
ipcMain.handle("show-main", () => {
  showWindow();
  return state;
});
ipcMain.handle("bubble-menu", () => {
  bubbleContextMenu();
  return state;
});
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
ipcMain.handle("set-codex-mode", (_event, codexMode) => {
  const allowed = ["one-time", "interactive"];
  if (!allowed.includes(codexMode)) {
    throw new Error(`Unsupported Codex mode: ${codexMode}`);
  }
  setState({ codexMode });
  return state;
});

app.whenReady().then(() => {
  createWindow();
  createBubbleWindow();
  tray = new Tray(createIcon(trayIconPath));
  tray.on("click", showWindow);
  updateTray();
  startWindowTracker();
});

app.on("before-quit", (event) => {
  if (quitAfterCleanup) return;
  event.preventDefault();
  quitApp();
});

app.on("window-all-closed", () => {
  if (isQuitting && process.platform !== "darwin") app.quit();
});
