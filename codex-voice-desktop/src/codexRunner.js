const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const { spawn } = require("node:child_process");
const CODEX_OUTPUT_INSTRUCTION = [
  "Use the same language as the user's request for both interpreting the request and reporting back.",
  "Do not output code, file paths, Markdown links, or logs.",
  "Use plain language to briefly report progress and the result."
].join(" ");
const SANDBOX_MODES = ["read-only", "workspace-write", "danger-full-access"];

function buildCodexPrompt(text) {
  return `${String(text || "").trim()}\n\n${CODEX_OUTPUT_INSTRUCTION}\n`;
}

function nowStamp() {
  const d = new Date();
  const pad = (n) => String(n).padStart(2, "0");
  return `${d.getFullYear()}${pad(d.getMonth() + 1)}${pad(d.getDate())}-${pad(d.getHours())}${pad(d.getMinutes())}${pad(d.getSeconds())}`;
}

function candidateCodexBins() {
  if (process.platform === "win32") {
    const appData = process.env.APPDATA || "";
    return [
      path.join(appData, "npm", "codex.cmd"),
      "codex.cmd",
      "codex"
    ];
  }
  return ["codex"];
}

function fileExists(file) {
  try {
    return fs.existsSync(file);
  } catch {
    return false;
  }
}

function resolveCodexBin(explicitBin) {
  if (explicitBin) return explicitBin;
  for (const candidate of candidateCodexBins()) {
    if (candidate.includes(path.sep) && fileExists(candidate)) return candidate;
    if (!candidate.includes(path.sep)) return candidate;
  }
  return process.platform === "win32" ? "codex.cmd" : "codex";
}

function runCommand(command, args, options = {}) {
  const timeoutMs = options.timeoutMs || 300000;
  return new Promise((resolve) => {
    const needsShell = process.platform === "win32" && /\.(cmd|bat)$/i.test(command);
    const child = spawn(
      needsShell ? (process.env.ComSpec || "cmd.exe") : command,
      needsShell ? ["/d", "/c", command, ...args] : args,
      {
      cwd: options.cwd,
      windowsHide: true,
      stdio: ["pipe", "pipe", "pipe"]
      }
    );

    let stdout = "";
    let stderr = "";
    let timedOut = false;
    const timer = setTimeout(() => {
      timedOut = true;
      child.kill("SIGTERM");
    }, timeoutMs);

    child.stdout.on("data", (chunk) => {
      stdout += chunk.toString("utf8");
    });
    child.stderr.on("data", (chunk) => {
      stderr += chunk.toString("utf8");
    });
    child.on("error", (error) => {
      clearTimeout(timer);
      resolve({ code: -1, stdout, stderr: `${stderr}${error.message}`, timedOut });
    });
    child.on("close", (code) => {
      clearTimeout(timer);
      resolve({ code: timedOut ? -2 : code, stdout, stderr, timedOut });
    });

    if (options.input) {
      child.stdin.write(options.input);
    }
    child.stdin.end();
  });
}

async function codexVersion(codexBin) {
  const bin = resolveCodexBin(codexBin);
  const result = await runCommand(bin, ["--version"], { timeoutMs: 30000 });
  return {
    bin,
    ok: result.code === 0,
    version: result.stdout.trim() || result.stderr.trim(),
    error: result.code === 0 ? "" : result.stderr.trim()
  };
}

async function submitTranscript(options) {
  const text = (options.text || "").trim();
  if (!text) {
    throw new Error("Transcript text is empty.");
  }

  const cwd = path.resolve(options.cwd || process.cwd());
  const outDir = path.resolve(options.outDir || path.join(cwd, ".desktop-test"));
  fs.mkdirSync(outDir, { recursive: true });

  const stamp = nowStamp();
  const transcriptPath = path.join(outDir, `${stamp}.transcript.txt`);
  const answerPath = path.join(outDir, `${stamp}.codex_answer.txt`);
  const logPath = path.join(outDir, `${stamp}.codex_log.txt`);
  fs.writeFileSync(transcriptPath, `${text}\n`, "utf8");

  const bin = resolveCodexBin(options.codexBin);
  const sandboxMode = options.sandboxMode || (options.readOnly ? "read-only" : "danger-full-access");
  if (!SANDBOX_MODES.includes(sandboxMode)) {
    throw new Error(`Unsupported Codex sandbox mode: ${sandboxMode}`);
  }
  const args = ["exec", "--skip-git-repo-check"];
  args.push("--sandbox", sandboxMode);
  args.push("-o", answerPath, "-");

  const result = await runCommand(bin, args, {
    cwd,
    input: buildCodexPrompt(text),
    timeoutMs: options.timeoutMs || 600000
  });

  const log = [
    `command: ${bin} ${args.join(" ")}`,
    `cwd: ${cwd}`,
    `exit: ${result.code}`,
    "",
    "stdout:",
    result.stdout,
    "",
    "stderr:",
    result.stderr
  ].join("\n");
  fs.writeFileSync(logPath, log, "utf8");

  const answer = fileExists(answerPath)
    ? fs.readFileSync(answerPath, "utf8").trim()
    : result.stdout.trim();

  return {
    ok: result.code === 0,
    code: result.code,
    transcriptPath,
    answerPath,
    logPath,
    answer,
    stderr: result.stderr.trim(),
    timedOut: result.timedOut
  };
}

function defaultPaths() {
  const appRoot = path.resolve(__dirname, "..");
  const devWorkspaceRoot = path.resolve(appRoot, "..");
  const voiceRoot = resolveVoiceRoot(appRoot, devWorkspaceRoot);
  const workspaceRoot = path.resolve(voiceRoot, "..");
  return {
    appRoot,
    workspaceRoot,
    voiceRoot,
    pythonBin: process.platform === "win32"
      ? path.join(voiceRoot, ".venv", "Scripts", "python.exe")
      : path.join(voiceRoot, ".venv", "bin", "python"),
    wlkBin: process.platform === "win32"
      ? path.join(voiceRoot, ".venv", "Scripts", "wlk.exe")
      : path.join(voiceRoot, ".venv", "bin", "wlk")
  };
}

function resolveVoiceRoot(appRoot, devWorkspaceRoot) {
  if (process.env.CODEX_VOICE_ROOT) {
    return path.resolve(process.env.CODEX_VOICE_ROOT);
  }

  const exeDir = path.dirname(process.execPath || "");
  const cwd = process.cwd();
  const resourcesPath = process.resourcesPath || "";
  const candidates = [
    path.join(devWorkspaceRoot, "codex-voice-wlk"),
    path.join(resourcesPath, "codex-voice-wlk"),
    path.join(cwd, "codex-voice-wlk"),
    path.join(cwd, "..", "codex-voice-wlk"),
    path.join(cwd, "..", "..", "codex-voice-wlk"),
    path.join(cwd, "..", "..", "..", "codex-voice-wlk"),
    path.join(exeDir, "codex-voice-wlk"),
    path.join(exeDir, "..", "codex-voice-wlk"),
    path.join(exeDir, "..", "..", "codex-voice-wlk"),
    path.join(exeDir, "..", "..", "..", "codex-voice-wlk")
  ];

  for (const candidate of candidates) {
    if (fileExists(path.join(candidate, "voice_bridge.py"))) {
      return path.resolve(candidate);
    }
  }

  return path.join(devWorkspaceRoot, "codex-voice-wlk");
}

module.exports = {
  codexVersion,
  buildCodexPrompt,
  defaultPaths,
  resolveCodexBin,
  runCommand,
  SANDBOX_MODES,
  submitTranscript
};
