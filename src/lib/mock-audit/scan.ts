import "server-only";
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join, relative } from "node:path";

// Server-side mock-leakage scan — the live data behind the System Health
// "Mock Data Status" surface (spec §18). Mirrors scripts/mock-audit.mjs so the
// dashboard and the CI gate agree.

const MOCK_IMPORT = /\bfrom\s+["']([^"']*(?:-mock|\/mock)[^"']*)["']/g;

export type MockLeakageReport = {
  scannedAt: string;
  totals: { sourceFiles: number; mockLibFiles: number; filesImportingMock: number; pageRoutesWithMock: number; componentsWithMock: number };
  topDomains: { domain: string; count: number }[];
  pagesWithMock: { page: string; mocks: string[] }[];
};

function walk(dir: string, out: string[] = []): string[] {
  for (const name of readdirSync(dir)) {
    const p = join(dir, name);
    if (statSync(p).isDirectory()) {
      if (name === "node_modules" || name === ".next") continue;
      walk(p, out);
    } else if (/\.(ts|tsx)$/.test(name)) out.push(p);
  }
  return out;
}
const isPage = (rel: string) => rel.startsWith("app/") && /\/page\.tsx$/.test(rel);
const domainOf = (spec: string) => spec.replace(/^@\/lib\//, "").replace(/(-mock|\/mock).*$/, "").split("/")[0] || spec;

let cache: { report: MockLeakageReport; at: number } | null = null;

export function scanMockLeakage(): MockLeakageReport {
  if (cache && Date.now() - cache.at < 60_000) return cache.report;
  const SRC = join(process.cwd(), "src");
  let files: string[] = [];
  try { files = walk(SRC); } catch { /* src not reachable in some runtimes */ }

  const pages: { file: string; mocks: string[] }[] = [];
  const components: { file: string; mocks: string[] }[] = [];
  const byDomain: Record<string, number> = {};
  let mockLibFiles = 0;

  for (const f of files) {
    const rel = relative(SRC, f);
    const isMockLib = /(-mock|\/mock)\.tsx?$/.test(rel) || /\/mock\//.test(rel);
    if (isMockLib) mockLibFiles++;
    let text = ""; try { text = readFileSync(f, "utf8"); } catch { continue; }
    const specs = [...text.matchAll(MOCK_IMPORT)].map((m) => m[1]);
    if (!specs.length || isMockLib) continue;
    const entry = { file: rel, mocks: [...new Set(specs)] };
    if (isPage(rel)) pages.push(entry); else components.push(entry);
    for (const s of specs) byDomain[domainOf(s)] = (byDomain[domainOf(s)] ?? 0) + 1;
  }

  const report: MockLeakageReport = {
    scannedAt: new Date().toISOString(),
    totals: { sourceFiles: files.length, mockLibFiles, filesImportingMock: pages.length + components.length, pageRoutesWithMock: pages.length, componentsWithMock: components.length },
    topDomains: Object.entries(byDomain).sort((a, b) => b[1] - a[1]).slice(0, 15).map(([domain, count]) => ({ domain, count })),
    pagesWithMock: pages.map((p) => ({ page: p.file.replace(/^app\//, "/").replace(/\/page\.tsx$/, "") || "/", mocks: p.mocks })).sort((a, b) => b.mocks.length - a.mocks.length),
  };
  cache = { report, at: Date.now() };
  return report;
}
