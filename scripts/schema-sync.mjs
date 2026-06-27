#!/usr/bin/env node
// ──────────────────────────────────────────────────────────────────────────
// Schema source-of-truth guard
// ──────────────────────────────────────────────────────────────────────────
//
// HISTORY
//   This script once kept TWO Prisma schemas in sync (root Next.js + the
//   legacy NestJS `edify-api`). That era ended when the NestJS backend was
//   deleted (commit 3099050) and Django became the single source of truth.
//
// CURRENT REALITY
//   • Django (edify-api) OWNS the database. Django models + migrations are the
//     canonical schema. `manage.py makemigrations --check --dry-run` (run by the
//     backend CI) is the real drift guard.
//   • The root `prisma/schema.prisma` + Prisma client are LEGACY/vestigial: the
//     web app reads through Django's REST API (`src/lib/api/surfaces.ts` →
//     `/api/*` proxy), not Prisma. No page imports the Prisma adapter. The
//     schema is retained only so legacy `src/server/*` modules and `prisma
//     generate` still type-check; it is no longer a second source of truth.
//
//   Because there is no longer a pair of schemas to reconcile, this command is
//   a no-op that exits 0. It is kept (rather than deleted) so `npm run ci` and
//   any external caller still resolve; deleting it would break the `ci` script.
//
// USAGE
//   node scripts/schema-sync.mjs check   # no-op — Django is canonical (exit 0)
//   node scripts/schema-sync.mjs sync    # no-op — nothing to sync (exit 0)
//
//   The authoritative drift checks are now:
//     • Backend:  (cd edify-api && python manage.py makemigrations --check --dry-run)
//     • Frontend: npm run typecheck   (catches legacy Prisma type drift)
// ──────────────────────────────────────────────────────────────────────────

const mode = process.argv[2] ?? "check";

if (mode === "check" || mode === "sync") {
  console.log(
    "✓ Schema source of truth: Django (edify-api) — root Prisma schema is legacy/vestigial. " +
      "Nothing to " + mode + "."
  );
  process.exit(0);
}

console.error(`Unknown mode "${mode}". Use "check" or "sync".`);
process.exit(2);
