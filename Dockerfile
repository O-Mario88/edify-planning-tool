# ── edify-web (Next.js, standalone) ──────────────────────────────────────────
FROM node:22-slim AS build
WORKDIR /app
# OpenSSL is required by Prisma's engines (generate + migrate).
RUN apt-get update && apt-get install -y --no-install-recommends openssl && rm -rf /var/lib/apt/lists/*
COPY package*.json ./
RUN npm ci
COPY . .
# Generate the Prisma Client (into node_modules/@prisma/client + .prisma) so it
# can be copied into the runtime image for the pre-deploy migrate/seed step.
# Uses the stub DATABASE_URL from prisma.config.ts — no DB needed at build time.
RUN npm run db:generate
# Server env (EDIFY_API_URL / EDIFY_USE_BACKEND) is read at REQUEST time, not
# baked in, so it stays runtime-configurable. Build only needs the source.
ENV NEXT_TELEMETRY_DISABLED=1
RUN npm run build

FROM node:22-slim AS runtime
WORKDIR /app
ENV NODE_ENV=production
ENV NEXT_TELEMETRY_DISABLED=1
ENV PORT=3000
ENV HOSTNAME=0.0.0.0
# OpenSSL — Prisma migrate/seed engines need it at runtime too.
RUN apt-get update && apt-get install -y --no-install-recommends openssl && rm -rf /var/lib/apt/lists/*
# The standalone server + its traced runtime deps, plus static assets + public.
COPY --from=build /app/.next/standalone ./
COPY --from=build /app/.next/static ./.next/static
COPY --from=build /app/public ./public

# ── Prisma for the pre-deploy step (`npm run db:migrate && npm run db:seed`) ──
# Next's standalone output traces ONLY the server's runtime deps, so the Prisma
# CLI, its engine binaries, the generated client, the schema, and the seed are
# absent — which is why the pre-deploy command failed with "prisma: not found".
# Copy the FULL node_modules from the build stage (it has: the prisma CLI + its
# .bin symlink, the generated @prisma/client + engines, the @prisma/adapter-pg
# driver adapter + pg and their transitive deps, and bcryptjs) plus the Prisma
# schema/config and the one source file the seed imports. This overwrites the
# standalone's partial node_modules with the complete set; `node server.js`
# still runs (the full tree is a superset). The standalone package.json (copied
# above) carries the npm scripts.
COPY --from=build /app/node_modules ./node_modules
COPY --from=build /app/prisma ./prisma
COPY --from=build /app/prisma.config.ts ./prisma.config.ts
COPY --from=build /app/src/lib/uganda-districts.ts ./src/lib/uganda-districts.ts

EXPOSE 3000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=5 \
  CMD node -e "fetch('http://localhost:'+(process.env.PORT||3000)+'/api/health').then(r=>process.exit(r.ok?0:1)).catch(()=>process.exit(1))"
CMD ["node", "server.js"]
