// The smoke check the lane runs inside a container: start the app, wait until
// it answers, request each path once, and stop it. The exit code is 0 only when
// every path answered with a 2xx status, so a step's outcome is the check's.
//
//   node smoke.mjs PORT PATH... -- COMMAND ARG...
//
// The app is started with PORT and HOST=127.0.0.1 in its environment, and what
// it printed is printed after the results, so a boot failure can be read in the
// step's output.
import { spawn } from "node:child_process";

const READY_WITHIN_MS = 30_000;

const args = process.argv.slice(2);
const split = args.indexOf("--");
if (split < 2 || split === args.length - 1) {
  console.error("usage: node smoke.mjs PORT PATH... -- COMMAND ARG...");
  process.exit(2);
}
const port = args[0];
const paths = args.slice(1, split);
const [command, ...commandArgs] = args.slice(split + 1);

const app = spawn(command, commandArgs, {
  env: { ...process.env, PORT: port, HOST: "127.0.0.1" },
  stdio: ["ignore", "pipe", "pipe"],
});
let printed = "";
app.stdout.on("data", (chunk) => (printed += chunk));
app.stderr.on("data", (chunk) => (printed += chunk));
let exited = null;
app.on("exit", (code, signal) => (exited = signal ?? code));

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

async function answered(path) {
  const response = await fetch(`http://127.0.0.1:${port}${path}`, {
    headers: { accept: path === "/" ? "text/html" : "application/json" },
  });
  return response.status;
}

async function main() {
  const deadline = Date.now() + READY_WITHIN_MS;
  let ready = false;
  while (Date.now() < deadline && exited === null) {
    try {
      await answered(paths[0]);
      ready = true;
      break;
    } catch {
      await sleep(250);
    }
  }
  if (!ready) {
    console.error(
      exited === null
        ? `the app did not answer on port ${port} within ${READY_WITHIN_MS / 1000}s`
        : `the app exited (${exited}) before it answered`,
    );
    return 1;
  }
  let failed = 0;
  for (const path of paths) {
    const status = await answered(path).catch((error) => `no answer (${error.message})`);
    const ok = typeof status === "number" && status >= 200 && status < 300;
    console.log(`GET ${path} ${status}${ok ? "" : "  FAILED"}`);
    if (!ok) failed += 1;
  }
  return failed ? 1 : 0;
}

const code = await main();
app.kill("SIGTERM");
if (printed.trim()) console.log(`--- the app printed ---\n${printed.trim()}`);
process.exit(code);
