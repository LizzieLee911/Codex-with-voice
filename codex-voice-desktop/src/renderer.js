const $ = (id) => document.getElementById(id);

const sandboxModes = [
  { value: "read-only", label: "Read only" },
  { value: "workspace-write", label: "Workspace write" },
  { value: "danger-full-access", label: "Full access" }
];

const els = {
  status: $("status"),
  language: $("language"),
  wlk: $("wlk"),
  codex: $("codex"),
  sandbox: $("sandbox"),
  sandboxLabel: $("sandboxLabel"),
  log: $("log"),
  start: $("start"),
  stop: $("stop")
};

function appendLog(line) {
  els.log.textContent += `${line}\n`;
  els.log.scrollTop = els.log.scrollHeight;
}

function currentSandboxMode() {
  return sandboxModes[Number(els.sandbox.value)]?.value || "danger-full-access";
}

function renderState(state) {
  const mode = state.mode || "stopped";
  const sandboxIndex = Math.max(0, sandboxModes.findIndex((item) => item.value === state.sandboxMode));

  els.status.textContent = state.status || "Unknown";
  els.status.dataset.mode = mode;
  els.language.textContent = state.detectedLanguage || "Waiting";
  els.wlk.textContent = state.wlk || "unknown";
  els.sandbox.value = String(sandboxIndex);
  els.sandboxLabel.textContent = sandboxModes[sandboxIndex].label;
  els.start.disabled = mode !== "stopped";
  els.stop.disabled = mode === "stopped";
  els.sandbox.disabled = mode !== "stopped";
}

async function refreshEnv() {
  const env = await window.voiceApp.env();
  renderState(env);
  els.codex.textContent = env.codex.ok ? env.codex.version : `not ready: ${env.codex.error}`;
}

async function runAction(label, action) {
  appendLog(`> ${label}`);
  try {
    const result = await action();
    if (result && result.status) renderState(result);
  } catch (error) {
    appendLog(`ERROR: ${error.message || error}`);
  }
}

els.start.addEventListener("click", () => runAction("Start", () => window.voiceApp.start()));
els.stop.addEventListener("click", () => runAction("Stop", () => window.voiceApp.stop()));
els.sandbox.addEventListener("input", () => {
  const mode = currentSandboxMode();
  els.sandboxLabel.textContent = sandboxModes[Number(els.sandbox.value)].label;
  runAction(`Sandbox: ${mode}`, () => window.voiceApp.setSandbox(mode));
});

window.voiceApp.onLog(appendLog);
window.voiceApp.onState(renderState);

refreshEnv().catch((error) => appendLog(`ERROR: ${error.message || error}`));
