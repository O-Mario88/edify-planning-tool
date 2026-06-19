// The single PrismaClient for the consolidated backend.
//
// Prisma 7 requires a driver adapter; edify-web standardised on @prisma/adapter-pg.
// We expose a `PrismaService` class (extends PrismaClient) so ported edify-api
// services keep their `constructor(private prisma: PrismaService)` signature
// unchanged, plus a `prisma` singleton the service container injects.
//
// The instance is memoised on globalThis so Next's dev HMR doesn't open a new
// connection pool on every reload (the pattern src/lib/infra/db.ts already used).
import { PrismaClient } from "@prisma/client";
import { PrismaPg } from "@prisma/adapter-pg";

export class PrismaService extends PrismaClient {
  constructor() {
    const connectionString = process.env.DATABASE_URL;
    if (!connectionString) {
      throw new Error(
        "DATABASE_URL is required for the edify-web server runtime (consolidated backend).",
      );
    }
    super({ adapter: new PrismaPg({ connectionString }) });
  }
}

const globalForPrisma = globalThis as unknown as {
  __edifyPrisma?: PrismaService;
};

export const prisma: PrismaService =
  globalForPrisma.__edifyPrisma ?? new PrismaService();

if (process.env.NODE_ENV !== "production") {
  globalForPrisma.__edifyPrisma = prisma;
}
