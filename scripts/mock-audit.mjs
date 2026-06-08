#!/usr/bin/env node
// Mock-leakage scanner (purge migration, spec §18).
//
// Walks src/ and reports which files import a frontend mock module. Real route
// PAGES importing mock are the leak that matters — the migration's goal is to
// drive that count to zero. Run as a gate:  node scripts/mock-audit.mjs --gate
// exits non-zero when any page route still imports mock.
//
// Usage:
//   node scripts/mock-audit.mjs           # print the report
//   node scripts/mock-audit.mjs --json    # machine-readable report
//   node scripts/mock-audit.mjs --gate    # exit 1 if pages import mock
//   node scripts/mock-audit.mjs --write   # write mock-audit-report.json

import { readdirSync, readFileSync, statSync, writeFileSync } from "node:fs";
import { join, relative } from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = join(fileURLToPath(new URL(".", import.meta.url)), "..");
const SRC = join(ROOT, "src");

// An import is a mock import when its module specifier contains "-mock" or a
// "/mock" segment (e.g. "@/lib/schools-mock", "@/lib/messages-v2/mock").
const MOCK_IMPORT = /\bfrom\s+["']([^"']*(?:-mock|\/mock)[^"']*)["']/g;

function walk(dir, out = []) {
  for (const name of readdirSync(dir)) {
    const p = join(dir, name);
    const s = statSync(p);
    if (s.isDirectory()) {
      if (name === "node_modules" || name === ".next") continue;
      walk(p, out);
    } else if (/\.(ts|tsx)$/.test(name)) {
      out.push(p);
    }
  }
  return out;
}

function isPage(rel) {
  return rel.startsWith("app/") && /\/page\.tsx$/.test(rel);
}
function domainOf(spec) {
  // "@/lib/schools-mock" -> "schools"; "@/lib/messages-v2/mock" -> "messages-v2"
  const m = spec.replace(/^@\/lib\//, "").replace(/(-mock|\/mock).*$/, "");
  return m.split("/")[0] || spec;
}

const files = walk(SRC);
const pages = [];
const components = [];
const byDomain = {};
let mockLibFiles = 0;

for (const f of files) {
  const rel = relative(SRC, f);
  if (/(-mock|\/mock)\.tsx?$/.test(rel) || /\/mock\//.test(rel)) mockLibFiles++;
  const text = readFileSync(f, "utf8");
  const specs = [...text.matchAll(MOCK_IMPORT)].map((m) => m[1]);
  if (specs.length === 0) continue;
  // Don't count the mock module itself importing a sibling mock.
  if (/(-mock|\/mock)\.tsx?$/.test(rel)) continue;
  const entry = { file: rel, mocks: [...new Set(specs)] };
  if (isPage(rel)) pages.push(entry); else components.push(entry);
  for (const s of specs) byDomain[domainOf(s)] = (byDomain[domainOf(s)] ?? 0) + 1;
}

const report = {
  scannedAt: new Date().toISOString(),
  totals: { sourceFiles: files.length, mockLibFiles, filesImportingMock: pages.length + components.length, pageRoutesWithMock: pages.length, componentsWithMock: components.length },
  topDomains: Object.entries(byDomain).sort((a, b) => b[1] - a[1]).slice(0, 15).map(([domain, count]) => ({ domain, count })),
  pagesWithMock: pages.map((p) => ({ page: p.file.replace(/^app\//, "/").replace(/\/page\.tsx$/, "") || "/", mocks: p.mocks })),
  productionSafe: (process.env.NEXT_PUBLIC_USE_MOCK_DATA ?? "false") !== "true",
};

const args = process.argv.slice(2);
if (args.includes("--json")) {
  process.stdout.write(JSON.stringify(report, null, 2) + "\n");
} else {
  const t = report.totals;
  console.log("\n  Mock-leakage audit");
  console.log("  ──────────────────");
  console.log(`  Source files scanned : ${t.sourceFiles}`);
  console.log(`  Mock library files   : ${t.mockLibFiles}`);
  console.log(`  Files importing mock : ${t.filesImportingMock}  (pages ${t.pageRoutesWithMock} · components ${t.componentsWithMock})`);
  console.log("\n  Top mock domains:");
  for (const d of report.topDomains) console.log(`    ${String(d.count).padStart(4)}  ${d.domain}`);
  console.log(`\n  Page routes still importing mock: ${t.pageRoutesWithMock}`);
  if (t.pageRoutesWithMock) console.log("  (run with --json for the full per-page list)\n");
}

if (args.includes("--write")) {
  writeFileSync(join(ROOT, "mock-audit-report.json"), JSON.stringify(report, null, 2));
  console.log("  wrote mock-audit-report.json");
}

if (args.includes("--gate") && report.totals.pageRoutesWithMock > 0) {
  console.error(`\n  ✗ GATE FAILED: ${report.totals.pageRoutesWithMock} page route(s) still import frontend mock data.\n`);
  process.exit(1);
}
