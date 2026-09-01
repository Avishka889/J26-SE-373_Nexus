import path from "path";
import { fileURLToPath } from "url";
import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig, loadEnv } from "vite";
import { parseLiveFeatures } from "./src/lib/liveFeatures";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

// https://vite.dev/config/
export default defineConfig(({ command, mode }) => {
  const env = loadEnv(mode, __dirname, "VITE_");
  // Checked here as well as at module load, so a mistyped feature name fails the
  // build instead of shipping. In the browser the same parser throws while the
  // bundle initialises, which is a blank page: correct, and a poor way to find
  // out. This is the same list, read through the same function, on the way in.
  parseLiveFeatures(env.VITE_LIVE_FEATURES);
  // A production build names the orchestrator it talks to. Without one it built,
  // booted and called localhost:8000 from wherever it was served, saying so only
  // in the browser's console. The fixture mode reads no backend and needs none.
  if (command === "build" && mode !== "fixtures" && !env.VITE_API_URL) {
    throw new Error(
      "VITE_API_URL is required for a production build: set it to the orchestrator's address, " +
        "for example `VITE_API_URL=https://api.example.org npm run build`.",
    );
  }

  return {
    plugins: [react(), tailwindcss()],
    resolve: {
      alias: {
        "@": path.resolve(__dirname, "src"),
        // Types only: every import from it is `import type`, erased at build
        // time, so the package needs no build step and never reaches the
        // bundle. The alias exists so the frontend compiles against the
        // generated contract types instead of a hand written copy.
        "@sdlc/contracts-ts": path.resolve(__dirname, "../packages/contracts-ts/src/index.ts"),
      },
    },
  };
});
