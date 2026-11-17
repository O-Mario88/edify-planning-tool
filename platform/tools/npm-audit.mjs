// The CI dependency audit: `npm audit --audit-level=high`, except for the
// advisories listed below, each until its review date. A listed advisory
// past its date fails the audit again, so an exception cannot outlive the
// reason it was granted.
//
//   node ../tools/npm-audit.mjs      (from platform/mobile or platform/web)

import { execFileSync } from "node:child_process";

// Owner, 2026-11-17: "Allow it for now". picomatch has no release outside
// the vulnerable range yet (<=4.0.7 is every published version); it reaches
// the apps only through build and test tooling. Remove the entry once a
// fixed picomatch ships and the lockfiles take it.
const ALLOWED = [
  {
    id: "GHSA-fc5q-39xc-vjpf",
    package: "picomatch",
    until: "2026-12-17",
    reason: "picomatch ReDoS with no patched release yet",
  },
];

const BLOCKING = new Set(["high", "critical"]);

function audit() {
  try {
    return execFileSync("npm", ["audit", "--json"], { encoding: "utf8", maxBuffer: 64 * 1024 * 1024 });
  } catch (error) {
    // npm audit exits non-zero whenever it finds anything; the report is
    // still on stdout.
    if (typeof error.stdout === "string" && error.stdout.trim()) {
      return error.stdout;
    }
    throw error;
  }
}

const report = JSON.parse(audit());
if (report.error) {
  console.error(`npm audit could not run: ${JSON.stringify(report.error)}`);
  process.exit(1);
}

const today = new Date().toISOString().slice(0, 10);
const advisories = new Map();
for (const [name, vulnerability] of Object.entries(report.vulnerabilities ?? {})) {
  for (const via of vulnerability.via ?? []) {
    // A string is a package that depends on a vulnerable one; the advisory
    // itself is listed under that package.
    if (typeof via !== "object" || !BLOCKING.has(via.severity)) {
      continue;
    }
    const id = (via.url ?? "").split("/").pop() || String(via.source);
    advisories.set(id, { id, name, severity: via.severity, title: via.title, url: via.url });
  }
}

let failed = false;
let allowedCount = 0;
for (const advisory of advisories.values()) {
  const allowed = ALLOWED.find((a) => a.id === advisory.id && a.package === advisory.name);
  if (allowed && today <= allowed.until) {
    allowedCount += 1;
    console.log(`allowed until ${allowed.until}: ${advisory.severity} ${advisory.name} ${advisory.id} (${allowed.reason})`);
    continue;
  }
  failed = true;
  const note = allowed ? ` (its exception ended ${allowed.until}: review it)` : "";
  console.error(`${advisory.severity}: ${advisory.name} ${advisory.title} ${advisory.url}${note}`);
}

if (failed) {
  process.exit(1);
}
console.log(`no high or critical advisory outside the allowed list (${allowedCount} allowed)`);
