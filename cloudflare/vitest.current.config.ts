import { cloudflareTest, readD1Migrations } from '@cloudflare/vitest-plugin';
import { defineConfig } from 'vitest/config';

export default defineConfig({
  plugins:[cloudflareTest(async()=>({
    wrangler:{configPath:'./wrangler.current.jsonc'},
    miniflare:{
      bindings:{SESSION_SECRET:'radar-current-test-secret-at-least-32-bytes',TEST_MIGRATIONS:await readD1Migrations('./migrations-current')},
      d1Databases:['DB'],
    },
  }))],
  test:{include:['test/**/*-current.test.ts'],setupFiles:['./test/apply-migrations.ts'],fileParallelism:false,testTimeout:30000,hookTimeout:30000},
});
