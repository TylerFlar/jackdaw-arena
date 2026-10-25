import react from "@vitejs/plugin-react";
import { createReadStream, statSync } from "node:fs";
import { extname, join, normalize, sep } from "node:path";
import { fileURLToPath } from "node:url";
import type { Plugin } from "vite";
import { defineConfig } from "vitest/config";

// In development and e2e the API runs separately; in production CloudFront routes /api and
// /auth to Lambda on the same origin, so the SPA never needs CORS.
const api = process.env.ARENA_API_URL ?? "http://127.0.0.1:8000";
// A remote API (ARENA_API_URL=https://arena.tylerflar.com, for UI work on real data) answers
// only for its own host name.
const changeOrigin = api.startsWith("https://");
const proxy = {
  "/api": { target: api, changeOrigin },
  "/auth": { target: api, changeOrigin },
};

/** Balatro's art in development: web/.art/ (infra/scripts/extract_art.py) at /art/, where the
 * site's bucket serves it. Builds never include it. */
function localArt(): Plugin {
  const root = fileURLToPath(new URL("./.art", import.meta.url));
  const types: Record<string, string> = { ".png": "image/png", ".json": "application/json", ".ttf": "font/ttf" };
  return {
    name: "local-art",
    apply: "serve",
    configureServer(server) {
      server.middlewares.use("/art", (req, res) => {
        const path = decodeURIComponent((req.url ?? "/").split("?")[0]!);
        const file = normalize(join(root, path));
        const found = file.startsWith(root + sep) && statSync(file, { throwIfNoEntry: false })?.isFile();
        if (!found) {
          res.statusCode = 404;
          res.end();
          return;
        }
        res.setHeader("Content-Type", types[extname(file)] ?? "application/octet-stream");
        createReadStream(file).pipe(res);
      });
    },
  };
}

export default defineConfig({
  plugins: [react(), localArt()],
  server: { port: 5173, proxy },
  preview: { port: 4173, host: true, proxy },
  build: { sourcemap: true },
  test: {
    environment: "jsdom",
    setupFiles: ["./src/test/setup.ts"],
    include: ["src/**/*.test.{ts,tsx}"],
    css: false,
  },
});
