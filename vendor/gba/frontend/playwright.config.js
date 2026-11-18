import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./tests",
  workers: 1,
  timeout: 30000,
  use: {
    baseURL: "http://127.0.0.1:5196",
    channel: process.env.PLAYWRIGHT_CHANNEL || "msedge",
    headless: true,
    viewport: { width: 1440, height: 1000 }
  },
  webServer: {
    command: "npm run dev -- --port 5196 --strictPort",
    url: "http://127.0.0.1:5196",
    reuseExistingServer: false,
    timeout: 30000
  }
});
