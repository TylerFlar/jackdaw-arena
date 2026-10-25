import { defineConfig, devices } from "@playwright/test";

// End-to-end tests run against the docker compose e2e stack (see docker-compose.yml).
export default defineConfig({
  testDir: "./e2e",
  timeout: 120_000,
  retries: 0,
  reporter: [["list"], ["html", { open: "never" }]],
  use: {
    baseURL: process.env.E2E_BASE_URL ?? "http://localhost:8080",
    trace: "retain-on-failure",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
});
