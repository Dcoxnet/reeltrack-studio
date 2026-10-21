import { spawn } from "node:child_process";
import { existsSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const frontend = path.join(root, "frontend");
const venv = path.join(root, "backend", ".venv");
const python = process.platform === "win32"
  ? path.join(venv, "Scripts", "python.exe")
  : path.join(venv, "bin", "python");
const nextCli = path.join(frontend, "node_modules", "next", "dist", "bin", "next");

if (!existsSync(python)) {
  console.error("Python окружение не найдено. Сначала выполни pnpm setup:python из корня проекта.");
  process.exit(1);
}
if (!existsSync(nextCli)) {
  console.error("Фронтенд-зависимости не найдены. Сначала выполни pnpm install из корня проекта.");
  process.exit(1);
}

const processes = [];
let stopping = false;

function stop(code = 0) {
  if (stopping) return;
  stopping = true;
  for (const child of processes) {
    if (child.exitCode === null && child.signalCode === null) child.kill("SIGTERM");
  }
  setTimeout(() => process.exit(code), process.platform === "win32" ? 1200 : 500).unref();
}

function launch(command, args, cwd, label) {
  const child = spawn(command, args, { cwd, stdio: "inherit", windowsHide: true });
  processes.push(child);
  child.on("error", (error) => {
    console.error(`[${label}] ${error.message}`);
    stop(1);
  });
  child.on("exit", (code, signal) => {
    if (!stopping) {
      if (signal) console.log(`[${label}] остановлен (${signal})`);
      else if (code !== 0) console.error(`[${label}] завершился с кодом ${code}`);
      stop(code ?? 1);
    }
  });
}

process.on("SIGINT", () => stop(0));
process.on("SIGTERM", () => stop(0));

console.log("ReelTrack Studio запускается…");
launch(python, ["-m", "uvicorn", "api:app", "--host", "127.0.0.1", "--port", "8000"], path.join(root, "backend"), "API");
launch(process.execPath, [nextCli, "dev", "--hostname", "127.0.0.1"], frontend, "Next.js");
console.log("UI:  http://127.0.0.1:3000\nAPI: http://127.0.0.1:8000/api/health\nНажми Ctrl+C, чтобы освободить порты.");
