import { defineConfig } from "vitest/config";

// Vitest config — runs the engine + lib tests under tests/.
// React component tests are intentionally NOT included here; UI
// coverage belongs to a separate Playwright/Cypress story.
//
// `resolve.tsconfigPaths: true` lets test files import "@/lib/foo"
// exactly as production code does, reading the alias straight from
// tsconfig.json (no plugin needed in Vite 6+).

export default defineConfig({
  resolve: { tsconfigPaths: true },
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
