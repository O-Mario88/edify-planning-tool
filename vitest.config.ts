import { defineConfig } from "vitest/config";
import { fileURLToPath } from "node:url";

// Vitest config — runs the engine + lib tests under tests/.
// React component tests are intentionally NOT included here; UI
// coverage belongs to a separate Playwright/Cypress story.
//
// `resolve.tsconfigPaths: true` lets test files import "@/lib/foo"
// exactly as production code does, reading the alias straight from
// tsconfig.json (no plugin needed in Vite 6+).
//
// `server-only` is a Next.js build-time marker that throws if imported
// outside a server bundle; in the node test env we alias it to a no-op
// stub so server-side modules (rate-limit, storage, …) can be imported.

export default defineConfig({
  resolve: {
    tsconfigPaths: true,
    alias: {
      "server-only": fileURLToPath(new URL("./tests/stubs/server-only.ts", import.meta.url)),
    },
  },
  test: {
    include: ["tests/**/*.test.ts"],
    environment: "node",
    coverage: {
      provider: "v8",
      reporter: ["text", "html", "lcov"],
      include: ["src/lib/**/*.ts"],
      exclude: [
        "src/lib/**/*-mock.ts",
        "src/lib/**/*-store.ts",
        "src/lib/**/types.ts",
        "src/lib/auth-public.ts",
      ],
      thresholds: {
        // Floors for the engines we explicitly own. Lift these as
        // tests grow. Failing the build is intentional — coverage
        // regressions on the load-bearing math should not ship.
        "src/lib/pace-status.ts":         { lines: 100, functions: 100, branches: 90 },
        "src/lib/target-counting.ts":     { lines: 100, functions: 100, branches: 100 },
        "src/lib/plan-cost-calculator.ts":{ lines: 70,  functions: 80,  branches: 60 },
      },
    },
  },
});
