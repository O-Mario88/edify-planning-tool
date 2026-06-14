#!/usr/bin/env node
// Frontend production-readiness gate (security Phase 5). Asserts the web app is
// safe to deploy: mock data disabled, backend wired, and no page route still
// imports frontend mock. Exits non-zero on any failure — wire into CI / deploy.
//
//   node scripts/prod-readiness.mjs
//
// In development this is EXPECTED to fail if you have mock opted-in — that is
// the gate working. Run it in the deploy environment / CI with production env.
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import { join, dirname } from "node:path";

const here = dirname(fileURLToPath(import.meta.url));
const fails = [];
const warns = [];

// 1) Mock data must be off in production.
if ((process.env.NEXT_PUBLIC_USE_MOCK_DATA ?? "false").toLowerCase() === "true") {
  fails.push("NEXT_PUBLIC_USE_MOCK_DATA=true — mock data must be disabled in production.");
}
// 2) The real backend must be wired.
if ((process.env.EDIFY_USE_BACKEND ?? "").toLowerCase() !== "true") {
  fails.push("EDIFY_USE_BACKEND must be 'true' in production (the app must read the real backend).");
}
// 3) NODE_ENV sanity.
if (process.env.NODE_ENV && process.env.NODE_ENV !== "production") {
  warns.push(`NODE_ENV is '${process.env.NODE_ENV}' — production build should run with NODE_ENV=production.`);
}

// 4) No page route may import frontend mock (reuse the mock-audit gate).
const gate = spawnSync(process.execPath, [join(here, "mock-audit.mjs"), "--gate"], { encoding: "utf8" });
if (gate.status !== 0) {
  fails.push("Mock-leakage gate failed: a page route still imports frontend mock (see `node scripts/mock-audit.mjs --json`).");
}

console.log("\n  Frontend production-readiness");
console.log("  ─────────────────────────────");
for (const w of warns) console.log(`  ⚠  ${w}`);
for (const f of fails) console.log(`  ✗  ${f}`);
if (fails.length === 0) {
  console.log("  ✓  Mock disabled, backend wired, no page imports mock.\n");
  process.exit(0);
}
console.error(`\n  GATE FAILED: ${fails.length} blocking issue(s). Do not deploy.\n`);
process.exit(1);
