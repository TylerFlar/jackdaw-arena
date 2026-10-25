import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

// In development and e2e the API runs separately; in production CloudFront routes /api and
// /auth to Lambda on the same origin, so the SPA never needs CORS.
const api = process.env.ARENA_API_URL ?? "http://127.0.0.1:8000";
const proxy = {
  "/api": { target: api, changeOrigin: false },
  "/auth": { target: api, changeOrigin: false },
};

export default defineConfig({
  plugins: [react()],
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
