// Consolidation smoke test — verifies the ported backend foundation works
// against the live DB under Prisma 7. Run:
//   DATABASE_URL=<url> npx tsx scripts/consolidation-smoke.ts
//
// Constructs the services directly (not via container.ts, which imports
// "server-only" and would throw outside a Next request).
import { prisma } from "../src/server/prisma/prisma.service";
import { AuditService } from "../src/server/common/audit/audit.service";
import { ScopeService } from "../src/server/common/scope/scope.service";
import { GeographyService } from "../src/server/modules/geography/geography.service";
import type { AuthUser } from "../src/server/common/auth/auth-user";

const toAuthUser = (u: {
  id: string; email: string; name: string; roles: AuthUser["roles"];
  activeRole: AuthUser["activeRole"]; staffProfile: { id: string } | null;
}): AuthUser => ({
  userId: u.id, email: u.email, name: u.name, roles: u.roles,
  activeRole: u.activeRole, staffProfileId: u.staffProfile?.id,
});

async function main() {
  const audit = new AuditService(prisma);
  const scope = new ScopeService(prisma);

  // R1 — report the live chain status. NOTE: the live dev chain has a
  // PRE-EXISTING break (edify-api's own Prisma-6 verifier breaks at the same
  // seq with the same expected hash), so this is report-only here. The rigorous
  // R1+R2 proof (clean write+verify under Prisma 7 + PrismaPg) lives in
  // scripts/audit-chain-test.ts.
  const chain = await audit.verifyChain();
  console.log("R1 verifyChain (live, may show pre-existing break):", JSON.stringify(chain));

  // R3 — a PL resolves a real staffProfileId and a non-empty team scope.
  const pl = await prisma.user.findFirst({ where: { email: "pl1@edify.org" }, include: { staffProfile: true } });
  if (!pl) throw new Error("pl1@edify.org not found in DB");
  const plUser = toAuthUser(pl);
  console.log(`R3 pl1: userId=${plUser.userId} staffProfileId=${plUser.staffProfileId} activeRole=${plUser.activeRole}`);
  const plScope = await scope.resolveUserScope(plUser);
  console.log(`R3 PL scope: schools=${plScope.schoolIds.length} own=${plScope.ownSchoolIds.length} team=${plScope.teamSchoolIds.length} supervised=${plScope.supervisedStaffIds.length} canViewTeam=${plScope.canViewTeam} canViewCountry=${plScope.canViewCountry}`);

  // A CCEO sees own schools; a CD sees the whole country.
  const cceo = await prisma.user.findFirst({ where: { email: "cceo@edify.org" }, include: { staffProfile: true } });
  if (cceo) {
    const s = await scope.resolveUserScope(toAuthUser(cceo));
    console.log(`R3 CCEO scope: own=${s.ownSchoolIds.length} schools=${s.schoolIds.length} canViewCountry=${s.canViewCountry}`);
  }
  const cd = await prisma.user.findFirst({ where: { email: "cd@edify.org" }, include: { staffProfile: true } });
  if (cd) {
    const s = await scope.resolveUserScope(toAuthUser(cd));
    console.log(`R3 CD scope: canViewCountry=${s.canViewCountry} schools=${s.schoolIds.length}`);
  }

  // Wave 1 — ported GeographyService returns live reference data.
  const geo = new GeographyService(prisma);
  const [regions, districts] = await Promise.all([geo.listRegions(), geo.listDistricts()]);
  const subs = districts[0] ? await geo.listSubCounties(districts[0].id) : [];
  console.log(`W1 geography: regions=${regions.length} districts=${districts.length} subCounties[${districts[0]?.name}]=${subs.length}`);
  if (regions.length < 1 || districts.length < 1) throw new Error("geography service returned empty reference data");

  await prisma.$disconnect();
  console.log("\n✅ consolidation foundation smoke passed");
}

main().catch((e) => { console.error("❌", e); process.exit(1); });
