// Prisma 7 config — replaces the legacy `url = env(...)` in datasource.
// Prisma Migrate + Studio read this to find the connection URL.
//
// Runtime queries do NOT use this — they read PrismaClient's
// constructor adapter or fall back to DATABASE_URL automatically.

import type { PrismaConfig } from "prisma";

export default {
  schema: "prisma/schema.prisma",
  migrations: {
    seed: "tsx prisma/seed.ts",
  },
  // Connection URL for migrate / studio. Read from env so deploys can
  // override per-environment. Falls back to a stub so `prisma validate`
  // works in CI without a real DB.
  datasource: {
    url: process.env.DATABASE_URL ?? "postgresql://stub@localhost:5432/stub",
  },
} satisfies PrismaConfig;
