import type { D1Migration } from "@cloudflare/vitest-plugin";

declare global {
  namespace Cloudflare {
    interface Env {
      DB: D1Database;
      ASSETS: Fetcher;
      SESSION_SECRET: string;
      RADAR_ALLOW_REGISTRATION: string;
      RADAR_ENV: string;
      TEST_MIGRATIONS: D1Migration[];
    }
  }
}

export {};
