const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const { buildCodexPrompt, codexVersion, defaultPaths, submitTranscript } = require("../src/codexRunner");

function assert(condition, message) {
  if (!condition) throw new Error(message);
}

async function fakeCodexTest() {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "codex-voice-desktop-"));
  const fake = path.join(root, process.platform === "win32" ? "fake-codex.cmd" : "fake-codex.sh");
  const script = process.platform === "win32"
    ? [
        "@echo off",
        "set out=",
        ":loop",
        "if \"%~1\"==\"\" goto doneargs",
        "if \"%~1\"==\"-o\" goto foundout",
        "shift",
        "goto loop",
        ":foundout",
        "shift",
        "set out=%~1",
        "shift",
        "goto loop",
        ":doneargs",
        "if not \"%out%\"==\"\" echo fake desktop answer>\"%out%\"",
        "exit /b 0"
      ].join("\n")
    : [
        "#!/usr/bin/env sh",
        "out=",
        "while [ \"$#\" -gt 0 ]; do",
        "  if [ \"$1\" = \"-o\" ]; then shift; out=\"$1\"; fi",
        "  shift",
        "done",
        "printf 'fake desktop answer\\n' > \"$out\""
      ].join("\n");
  fs.writeFileSync(fake, `${script}\n`, "utf8");
  if (process.platform !== "win32") fs.chmodSync(fake, 0o755);

  const result = await submitTranscript({
    text: "fake transcript",
    cwd: root,
    outDir: path.join(root, "out"),
    codexBin: fake,
    timeoutMs: 30000
  });
  assert(result.ok, "fake Codex runner should succeed");
  assert(result.answer === "fake desktop answer", "fake answer should be captured");
  assert(fs.readFileSync(result.logPath, "utf8").includes("--sandbox danger-full-access"), "default sandbox should be full access");
  return result;
}

async function realCodexTest(paths) {
  const fixture = path.resolve(__dirname, "..", "fixtures", "fake-transcript.txt");
  const text = fs.readFileSync(fixture, "utf8");
  return submitTranscript({
    text,
    cwd: paths.appRoot,
    outDir: path.join(paths.appRoot, ".desktop-test"),
    readOnly: true,
    timeoutMs: 600000
  });
}

async function main() {
  const paths = defaultPaths();
  console.log("appRoot:", paths.appRoot);
  console.log("voiceRoot:", paths.voiceRoot);
  assert(fs.existsSync(paths.voiceRoot), "voice root is missing");
  assert(fs.existsSync(paths.pythonBin), "voice venv Python is missing");
  assert(fs.existsSync(path.join(paths.voiceRoot, "voice_bridge.py")), "voice_bridge.py is missing");
  assert(buildCodexPrompt("hello").includes("Use the same language"), "Codex prompt should preserve request language");

  const version = await codexVersion();
  console.log("codex:", version.bin, version.version || version.error);
  assert(version.ok, "Codex CLI is not available");

  const fake = await fakeCodexTest();
  console.log("fake submit answer:", fake.answer);

  if (process.argv.includes("--real-codex")) {
    const real = await realCodexTest(paths);
    console.log("real submit ok:", real.ok);
    console.log("real answer:", real.answer);
    console.log("real log:", real.logPath);
    assert(real.ok, "real Codex transcript submit failed");
    assert(real.answer.length > 0, "real Codex answer is empty");
  }
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
