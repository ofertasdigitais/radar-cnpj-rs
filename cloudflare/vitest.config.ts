import { cloudflareTest, readD1Migrations } from "@cloudflare/vitest-plugin";
import { defineConfig } from "vitest/config";

export default defineConfig({
  plugins: [
    cloudflareTest(async () => ({
      wrangler: { configPath: "./wrangler.jsonc" },
      miniflare: {
        bindings: {
          SESSION_SECRET: "radar-test-session-secret-with-at-least-32-bytes",
          TEST_MIGRATIONS: await readD1Migrations("./migrations"),
        },
        d1Databases: ["DB"],
      },
    })),
  ],
  test: {
    setupFiles: ["./test/apply-migrations.ts"],
  },
});
