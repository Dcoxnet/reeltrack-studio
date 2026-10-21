import { spawnSync } from "node:child_process";
import { existsSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const backend = path.join(root, "backend");
const venv = path.join(backend, ".venv");
const pythonInVenv = process.platform === "win32"
  ? path.join(venv, "Scripts", "python.exe")
  : path.join(venv, "bin", "python");

function run(command, args, options = {}) {
  const result = spawnSync(command, args, { cwd: root, stdio: "inherit", ...options });
  if (result.error) throw result.error;
  if (result.status !== 0) process.exit(result.status ?? 1);
}

function canRun(command, args) {
  const result = spawnSync(command, args, { encoding: "utf8", shell: process.platform === "win32" });
  if (result.error || result.status !== 0) return false;
  const version = `${result.stdout ?? ""}${result.stderr ?? ""}`.match(/Python (\d+)\.(\d+)/i);
  return !!version && (Number(version[1]) > 3 || (Number(version[1]) === 3 && Number(version[2]) >= 13));
}

const candidates = process.platform === "win32"
  ? [["py", ["-3.13", "--version"]], ["python", ["--version"]]]
  : [["python3.13", ["--version"]], ["python3", ["--version"]], ["python", ["--version"]]];
const python = candidates.find(([command, args]) => canRun(command, args));

if (!python) {
  console.error("Python 3.13+ не найден. Установи Python 3.13 и повтори pnpm setup:python.");
  console.error("Windows: установи Python с python.org и включи Python Launcher. Linux/macOS: установи Python 3.13 через пакетный менеджер.");
  process.exit(1);
}

if (!existsSync(pythonInVenv)) {
  console.log("Создаю Python окружение…");
  run(python[0], [...python[1].slice(0, -1), "-m", "venv", venv]);
}

console.log("Обновляю pip и устанавливаю зависимости API…");
run(pythonInVenv, ["-m", "pip", "install", "--upgrade", "pip"]);
run(pythonInVenv, ["-m", "pip", "install", "-r", path.join(backend, "requirements.txt")]);

const hasFfmpeg = canRun("ffmpeg", ["-version"]);
const hasFfprobe = canRun("ffprobe", ["-version"]);
if (!hasFfmpeg || !hasFfprobe) {
  console.warn("\nFFmpeg/ffprobe не найдены в PATH. Установи FFmpeg перед обработкой аудио:");
  if (process.platform === "win32") console.warn("Windows: установи FFmpeg и добавь папку bin в PATH.");
  else if (process.platform === "darwin") console.warn("macOS: brew install ffmpeg");
  else console.warn("Linux: установи пакет ffmpeg через пакетный менеджер (например, sudo pacman -S ffmpeg на CachyOS).");
} else {
  console.log("FFmpeg и ffprobe найдены.");
}

console.log("\nГотово. Запусти приложение командой pnpm dev из корня проекта.");
