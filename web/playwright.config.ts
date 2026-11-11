import { defineConfig, devices } from "@playwright/test";

// End-to-end tests run against the production build served by `astro preview`; every
// test runs twice, once per colour scheme, so both themes stay accessible.
export default defineConfig({
  testDir: "./e2e",
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? "list" : "html",
  use: {
    baseURL: "http://127.0.0.1:4321",
  },
  webServer: {
    // Not `astro preview`: in Astro 7 it forks a background daemon and the foreground
    // process exits, which Playwright treats as the server dying.
    command: "npx http-server dist -a 127.0.0.1 -p 4321 -s",
    url: "http://127.0.0.1:4321",
    reuseExistingServer: !process.env.CI,
  },
  projects: [
    {
      name: "light",
      use: { ...devices["Desktop Chrome"], colorScheme: "light" },
    },
    {
      name: "dark",
      use: { ...devices["Desktop Chrome"], colorScheme: "dark" },
    },
  ],
});
