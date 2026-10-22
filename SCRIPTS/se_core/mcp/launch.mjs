#!/usr/bin/env node
// Portable launcher for the SE Python MCP servers.
//
// OpenCode (and the npx-based MCPs) already require Node, but the Python
// command itself is not portable: Linux/macOS expose `python3`, while a
// Windows install usually exposes only `python`. Keeping either spelling in a
// version-tracked `opencode.jsonc` breaks the other platform.
//
// This launcher is invoked with Node and resolves the interpreter at runtime,
// preferring the native spelling for the host and falling back to the other
// one. Set `SE_PYTHON` to force a specific interpreter.

import { spawn, spawnSync } from "node:child_process";
import { existsSync } from "node:fs";
import path from "node:path";
import process from "node:process";

const [scriptArg, ...serverArgs] = process.argv.slice(2);

if (!scriptArg) {
  console.error("usage: node launch.mjs <python-script> [args...]");
  process.exit(2);
}

const script = path.isAbsolute(scriptArg)
  ? scriptArg
  : path.resolve(process.cwd(), scriptArg);

if (!existsSync(script)) {
  console.error(`SE MCP launcher: Python script not found: ${script}`);
  process.exit(2);
}

function pythonCandidates() {
  const native = process.platform === "win32"
    ? ["python", "python3"]
    : ["python3", "python"];
  const override = process.env.SE_PYTHON;
  return override ? [override, ...native] : native;
}

function resolvePython() {
  const seen = new Set();
  for (const candidate of pythonCandidates()) {
    if (!candidate || seen.has(candidate)) {
      continue;
    }
    seen.add(candidate);
    const probe = spawnSync(candidate, ["--version"], {
      stdio: "ignore",
      windowsHide: true,
    });
    if (!probe.error && probe.status === 0) {
      return candidate;
    }
  }
  return null;
}

const python = resolvePython();
if (!python) {
  console.error(
    "SE MCP launcher: Python 3 was not found. " +
    "Install Python 3 or set SE_PYTHON to the interpreter path.",
  );
  process.exit(127);
}

const child = spawn(python, [script, ...serverArgs], {
  stdio: "inherit",
  env: process.env,
  windowsHide: true,
});

child.on("error", (error) => {
  console.error(`SE MCP launcher: could not start ${python}: ${error.message}`);
  process.exit(1);
});

for (const signal of ["SIGINT", "SIGTERM"]) {
  process.on(signal, () => {
    if (!child.killed) {
      try {
        child.kill(signal);
      } catch {
        // The child may already be gone; the exit handler still runs.
      }
    }
  });
}

child.on("exit", (code, signal) => {
  process.exit(code ?? (signal ? 1 : 0));
});
