#!/usr/bin/env node
// Data-contract audit — scans the frontend for risky access patterns that can
// reach a backend payload's nested data without schema validation, the class of
// bug that crashes SSR with "Cannot read properties of undefined (reading 'map')".
//
// Usage:
//   node scripts/contract-audit.mjs            # report (always exit 0)
//   node scripts/contract-audit.mjs --strict   # exit 1 if any CRITICAL finding
//
// Heuristics (regex, intentionally conservative to avoid noise):
//   CRITICAL  raw collection op on a fetcher result's nested data, e.g.
//             `result.data.items.map(` / `.data.rows.filter(` in a NON-client file.
//   WARN      a `live<...>()` fetcher in surfaces.ts that passes no schema.
//   INFO      Object.entries/keys on a `.data.*` expression.

import { readFileSync, readdirSync, statSync } from "node:fs";
import { join, relative } from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = join(fileURLToPath(new URL(".", import.meta.url)), "..");
const SRC = join(ROOT, "src");

const strict = process.argv.includes("--strict");

/** @type {{file:string,line:number,risk:'CRITICAL'|'WARN'|'INFO',snippet:string,fix:string}[]} */
const findings = [];

function walk(dir) {
  for (const name of readdirSync(dir)) {
    const p = join(dir, name);
    const s = statSync(p);
    if (s.isDirectory()) {
      if (name === "node_modules" || name === ".next") continue;
      walk(p);
    } else if (/\.(ts|tsx)$/.test(name) && !/\.(test|spec)\.tsx?$/.test(name)) {
      scan(p);
    }
  }
}

// `<base>.data.<field>.<op>(` — a collection op directly on a nested fetcher
// payload. We capture <base> so we can check whether it was live-guarded.
const RAW_OP = /([A-Za-z0-9_]+)\.data\.[A-Za-z0-9_]+\.(map|filter|reduce|forEach|some|every|flatMap)\(/;
const OBJ_ENTRIES = /(Object\.(entries|keys|values)\s*\(\s*[A-Za-z0-9_]+\.data\.)/;

function scan(file) {
  const rel = relative(ROOT, file);
  const text = readFileSync(file, "utf8");
  const isClient = /^\s*["']use client["']/m.test(text);
  const lines = text.split("\n");

  lines.forEach((line, i) => {
    const ln = i + 1;
    const trimmed = line.trim();
    if (trimmed.startsWith("//") || trimmed.startsWith("*")) return;

    const m = RAW_OP.exec(line);
    if (m && !isClient) {
      const base = m[1];
      // A `<base>.live` guard in the file means the section is contained (and,
      // for schema-wired fetchers, validated). Unguarded raw maps are the real
      // SSR crash vector → CRITICAL; guarded ones are reported as WARN.
      const guarded = new RegExp(`${base}\\.live`).test(text) || new RegExp(`!${base}\\.live`).test(text);
      findings.push({
        file: rel,
        line: ln,
        risk: guarded ? "WARN" : "CRITICAL",
        snippet: trimmed.slice(0, 120),
        fix: guarded
          ? "Guarded by .live — ensure the fetcher passes a { schema } so live:true means validated arrays."
          : "Unguarded raw map on backend payload. Guard with !result.live and route through a schema-validated fetcher.",
      });
    }
    if (OBJ_ENTRIES.test(line) && !isClient) {
      findings.push({
        file: rel,
        line: ln,
        risk: "INFO",
        snippet: trimmed.slice(0, 120),
        fix: "Validate the object shape before Object.entries/keys to avoid iterating undefined.",
      });
    }
  });

  // Fetchers without a schema in the surfaces layer.
  if (rel.endsWith("src/lib/api/surfaces.ts")) {
    lines.forEach((line, i) => {
      if (/return live</.test(line)) {
        // Look ahead a few lines for a `schema:` mention in the same call.
        const window = lines.slice(i, i + 6).join(" ");
        if (!/schema:/.test(window)) {
          findings.push({
            file: rel,
            line: i + 1,
            risk: "WARN",
            snippet: line.trim().slice(0, 120),
            fix: "Add { schema } so live:true means validated data when this surface feeds a server component that maps over it.",
          });
        }
      }
    });
  }
}

walk(SRC);

const byRisk = { CRITICAL: [], WARN: [], INFO: [] };
for (const f of findings) byRisk[f.risk].push(f);

function print(group) {
  if (!group.length) return;
  for (const f of group) {
    console.log(`  ${f.risk.padEnd(8)} ${f.file}:${f.line}`);
    console.log(`           ${f.snippet}`);
    console.log(`           ↳ ${f.fix}`);
  }
}

console.log("\nData-Contract Audit\n===================");
console.log(`CRITICAL: ${byRisk.CRITICAL.length}  WARN: ${byRisk.WARN.length}  INFO: ${byRisk.INFO.length}\n`);
if (byRisk.CRITICAL.length) {
  console.log("CRITICAL — raw collection op on unvalidated nested payload (server side):");
  print(byRisk.CRITICAL);
}
if (byRisk.WARN.length) {
  console.log("\nWARN — guarded raw map / live fetcher without a schema:");
  print(byRisk.WARN);
}
if (byRisk.INFO.length) {
  console.log("\nINFO — Object iteration on .data.*:");
  print(byRisk.INFO);
}

if (strict && byRisk.CRITICAL.length) {
  console.error(`\n✖ ${byRisk.CRITICAL.length} critical contract finding(s).`);
  process.exit(1);
}
console.log("\n✔ audit complete");
