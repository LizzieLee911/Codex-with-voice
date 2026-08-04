const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const { spawnSync } = require("node:child_process");

const appRoot = path.resolve(__dirname, "..");
const distDir = path.join(appRoot, "dist");
const exePath = path.join(distDir, "Codex Voice Companion.exe");
const iconPath = path.join(appRoot, "assets", "app-icon.ico");
const desktop = path.join(os.homedir(), "Desktop");
const shortcutPath = path.join(desktop, "Codex Voice Companion.lnk");

function ps(value) {
  return `'${String(value).replace(/'/g, "''")}'`;
}

if (!fs.existsSync(exePath)) {
  console.error(`Portable app not found: ${exePath}`);
  console.error("Run npm run dist:portable first.");
  process.exit(1);
}

const script = [
  "$shell = New-Object -ComObject WScript.Shell",
  `$shortcut = $shell.CreateShortcut(${ps(shortcutPath)})`,
  `$shortcut.TargetPath = ${ps(exePath)}`,
  `$shortcut.WorkingDirectory = ${ps(distDir)}`,
  `$shortcut.IconLocation = ${ps(`${iconPath},0`)}`,
  "$shortcut.Save()"
].join("; ");

const result = spawnSync("powershell.exe", [
  "-NoProfile",
  "-ExecutionPolicy",
  "Bypass",
  "-Command",
  script
], { stdio: "inherit" });

if (result.status !== 0) {
  process.exit(result.status || 1);
}

console.log(`Created shortcut: ${shortcutPath}`);
