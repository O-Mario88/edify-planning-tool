#!/usr/bin/env node
// ──────────────────────────────────────────────────────────────────────────
// Prisma schema sync + drift guard
// ──────────────────────────────────────────────────────────────────────────
//
// WHY THIS EXISTS
//   The app runs two Prisma clients against ONE database:
//     • root Next.js app  → prisma/schema.prisma            (Prisma 7.x)
//     • edify-api (NestJS) → edify-api/prisma/schema.prisma (Prisma 6.x)
//   The model/enum/type definitions MUST stay identical, or a query that
//   compiles against one client throws a runtime type error against the other.
//
//   A plain symlink is NOT safe here: the two apps are on different Prisma
//   MAJOR versions, so their `datasource db { … }` blocks legitimately differ
//   (root supplies the URL via prisma.config.ts; edify-api uses the legacy
//   inline `url = env("DATABASE_URL")`). Symlinking would force one runtime to
//   use the other's datasource config and break its connection.
//
// THE MODEL
//   The ROOT schema (prisma/schema.prisma) is the SINGLE SOURCE OF TRUTH for
//   models/enums/types. The edify-api schema is a generated mirror: identical
//   body, its own datasource block.
//
// WORKFLOW
//   1. Edit models ONLY in the root schema:  prisma/schema.prisma
//   2. Propagate to edify-api:                npm run schema:sync
//   3. CI fails on drift:                     npm run schema:check
//      (wired into `npm run ci`)
//
// USAGE
//   node scripts/schema-sync.mjs check   # assert bodies identical (exit 1 on drift)
//   node scripts/schema-sync.mjs sync    # copy canonical body → edify-api schema
// ──────────────────────────────────────────────────────────────────────────

import { readFileSync, writeFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const CANONICAL = path.join(ROOT, "prisma/schema.prisma");
const MIRROR = path.join(ROOT, "edify-api/prisma/schema.prisma");

// The single legitimate difference: the `datasource db { … }` block. Everything
// else (generator + all enums/models/types) must match byte-for-byte.
const DATASOURCE = /datasource\s+db\s*\{[\s\S]*?\n\}\n/;

function bodyWithoutDatasource(src) {
  if (!DATASOURCE.test(src)) throw new Error("No `datasource db { … }` block found");
  return src.replace(DATASOURCE, "\n");
}

function datasourceBlock(src) {
  const m = src.match(DATASOURCE);
  if (!m) throw new Error("No `datasource db { … }` block found");
  return m[0];
}

function firstDivergence(a, b) {
  const al = a.split("\n");
  const bl = b.split("\n");
  const n = Math.max(al.length, bl.length);
  for (let i = 0; i < n; i++) {
    if (al[i] !== bl[i]) {
      return { line: i + 1, canonical: al[i] ?? "<missing>", mirror: bl[i] ?? "<missing>" };
    }
  }
  return null;
}

const mode = process.argv[2] ?? "check";
const canonical = readFileSync(CANONICAL, "utf8");
const mirror = readFileSync(MIRROR, "utf8");

if (mode === "check") {
  const a = bodyWithoutDatasource(canonical);
  const b = bodyWithoutDatasource(mirror);
  if (a === b) {
    console.log("✓ Prisma schema bodies are in sync (datasource blocks differ by Prisma version — expected).");
    process.exit(0);
  }
  const d = firstDivergence(a, b);
  console.error("✗ Prisma schema DRIFT detected between:");
  console.error(`    canonical: ${path.relative(ROOT, CANONICAL)}`);
  console.error(`    mirror:    ${path.relative(ROOT, MIRROR)}`);
  if (d) {
    console.error(`\n  First divergence near body line ${d.line}:`);
    console.error(`    canonical: ${d.canonical}`);
    console.error(`    mirror:    ${d.mirror}`);
  }
  console.error("\n  Fix: edit ONLY the root schema, then run `npm run schema:sync`.");
  process.exit(1);
} else if (mode === "sync") {
  // Canonical body + the mirror's own (Prisma-6) datasource block.
  const mirrorDatasource = datasourceBlock(mirror);
  const synced = canonical.replace(DATASOURCE, () => mirrorDatasource);
  if (synced === mirror) {
    console.log("✓ edify-api schema already up to date — nothing to sync.");
    process.exit(0);
  }
  writeFileSync(MIRROR, synced);
  console.log(`✓ Synced ${path.relative(ROOT, MIRROR)} from canonical ${path.relative(ROOT, CANONICAL)}.`);
  console.log("  Remember to run prisma generate / create a migration in BOTH apps.");
} else {
  console.error(`Unknown mode "${mode}". Use "check" or "sync".`);
  process.exit(2);
}
