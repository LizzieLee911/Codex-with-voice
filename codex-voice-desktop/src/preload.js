const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("voiceApp", {
  env: () => ipcRenderer.invoke("env"),
  start: () => ipcRenderer.invoke("start"),
  stop: () => ipcRenderer.invoke("stop"),
  openTurns: () => ipcRenderer.invoke("open-turns"),
  setWorkspace: (workspace) => ipcRenderer.invoke("set-workspace", workspace),
  setSandbox: (sandboxMode) => ipcRenderer.invoke("set-sandbox", sandboxMode),
  setCodexMode: (codexMode) => ipcRenderer.invoke("set-codex-mode", codexMode),
  onLog: (handler) => ipcRenderer.on("log", (_event, line) => handler(line)),
  onState: (handler) => ipcRenderer.on("state", (_event, state) => handler(state))
});
