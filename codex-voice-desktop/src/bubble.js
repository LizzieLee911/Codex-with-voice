const bubble = document.getElementById("bubble");
let clickTimer = null;

function renderState(state) {
  const mode = state?.mode || "stopped";
  const normalized = state?.status === "Restarting" ? "restarting" : mode;
  bubble.dataset.mode = normalized;
  bubble.title = `Codex Voice: ${state?.status || "Stopped"}`;
}

bubble.addEventListener("click", (event) => {
  if (event.detail !== 1) return;
  clickTimer = setTimeout(() => {
    clickTimer = null;
    window.voiceApp.toggle().catch(() => {});
  }, 180);
});

bubble.addEventListener("dblclick", () => {
  if (clickTimer) {
    clearTimeout(clickTimer);
    clickTimer = null;
  }
  window.voiceApp.showMain().catch(() => {});
});

bubble.addEventListener("contextmenu", (event) => {
  event.preventDefault();
  window.voiceApp.bubbleMenu().catch(() => {});
});

window.voiceApp.onState(renderState);
