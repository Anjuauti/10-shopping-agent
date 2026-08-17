import { existsSync } from "node:fs";
import { spawn } from "node:child_process";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const scriptDirectory = dirname(fileURLToPath(import.meta.url));
const frontendDirectory = resolve(scriptDirectory, "..");
const projectDirectory = resolve(frontendDirectory, "..");
const environmentPython = resolve(
  projectDirectory,
  "../.venv/Scripts/python.exe",
);
const python = existsSync(environmentPython) ? environmentPython : "python";
const vite = resolve(frontendDirectory, "node_modules/vite/bin/vite.js");

console.log("Starting the shopping API at http://127.0.0.1:8011...");
const api = spawn(
  python,
  ["-m", "uvicorn", "api:app", "--host", "127.0.0.1", "--port", "8011"],
  { cwd: projectDirectory, stdio: "inherit", windowsHide: true },
);

api.on("error", (error) => {
  console.error(`Could not start the shopping API: ${error.message}`);
});

console.log("Starting the React app...");
const client = spawn(process.execPath, [vite, ...process.argv.slice(2)], {
  cwd: frontendDirectory,
  stdio: "inherit",
  windowsHide: true,
});

function stop(processToStop) {
  if (!processToStop.killed) processToStop.kill();
}

function closeAll(exitCode = 0) {
  stop(api);
  stop(client);
  process.exit(exitCode);
}

api.on("exit", (code) => {
  if (code && !client.killed) {
    console.error(`Shopping API stopped unexpectedly (exit code ${code}).`);
    closeAll(code);
  }
});
client.on("exit", (code) => closeAll(code ?? 0));
process.on("SIGINT", () => closeAll());
process.on("SIGTERM", () => closeAll());
