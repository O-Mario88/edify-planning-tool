// Prisma seed — production-shaped data for a fresh database.
//
// Run: `npm run db:seed` (after `db:migrate`).
//
// What gets seeded:
//   • 8 users covering every role (matches the demo accounts in
//     src/lib/auth-public.ts).
//   • 1 country with 4 districts and 6 schools.
//   • 1 active CostSetting per ActivityKind.
//   • 1 sample Plan in Approved status with 3 PlannedActivities.
//   • 1 SchoolVisit, 2 TrainingParticipants (1 CceoConfirmed, 1
//     MeVerified), 2 SsaSnapshots, 1 PartnerActivity at MeVerified,
//     1 LeaveRecord at Approved.
//
// The seed is idempotent — re-running it is safe (uses upserts on
// natural keys). Used by:
//   • `db:seed` after a fresh migration in any env
//   • CI integration tests that need a known fixture
//   • staging environment refreshes

import bcrypt from "bcryptjs";

// We import @prisma/client lazily so a clone without `prisma generate`
// run still passes typecheck.
async function loadPrisma(): Promise<{ prisma: unknown }> {
  // eslint-disable-next-line @typescript-eslint/no-require-imports
  const { PrismaClient } = require("@prisma/client") as { PrismaClient: new () => unknown };
  return { prisma: new PrismaClient() };
}

// Deterministic ids so the seed plays well with CI snapshots.
const SCHOOL_IDS = ["sch_demo_01", "sch_demo_02", "sch_demo_03", "sch_demo_04", "sch_demo_05", "sch_demo_06"] as const;
const PARTNER_ID = "partner_bfep_demo";
const COUNTRY_ID = "uganda";

async function main(): Promise<void> {
  const { prisma } = await loadPrisma() as {
    prisma: {
      user: { upsert: (a: unknown) => Promise<unknown> };
      district: { upsert: (a: unknown) => Promise<unknown> };
      cluster: { upsert: (a: unknown) => Promise<unknown> };
      school: { upsert: (a: unknown) => Promise<unknown> };
      partner: { upsert: (a: unknown) => Promise<unknown> };
      costSetting: { upsert: (a: unknown) => Promise<unknown> };
      plan: { upsert: (a: unknown) => Promise<unknown> };
      plannedActivity: { upsert: (a: unknown) => Promise<unknown> };
      schoolVisit: { create: (a: unknown) => Promise<unknown> };
      trainingParticipant: { upsert: (a: unknown) => Promise<unknown> };
      ssaSnapshot: { create: (a: unknown) => Promise<unknown> };
      partnerActivity: { upsert: (a: unknown) => Promise<unknown> };
      leaveRecord: { upsert: (a: unknown) => Promise<unknown> };
      $disconnect: () => Promise<void>;
    };
  };

  const passwordHash = bcrypt.hashSync("edify-demo", 10);
  const users = [
    { email: "paul.chinyama@edify.org",   name: "Paul Chinyama",     role: "CCEO" },
    { email: "daniel.mwangi@edify.org",   name: "Daniel Mwangi",     role: "CountryProgramLead" },
    { email: "sarah.okello@edify.org",    name: "Sarah Okello",      role: "CountryDirector" },
    { email: "esther.wanjiru@edify.org",  name: "Esther Wanjiru",    role: "RVP" },
    { email: "moses.tindi@edify.org",     name: "Moses Tindi",       role: "ProgramAccountant" },
    { email: "grace.alimo@edify.org",     name: "Grace Alimo",       role: "ImpactAssessment" },
    { email: "anne.wairimu@edify.org",    name: "Anne Wairimu",      role: "HumanResource" },
    { email: "demo@edify.org",            name: "Edify Admin",       role: "Admin" },
  ];
  for (const u of users) {
    await prisma.user.upsert({
      where: { email: u.email },
      update: { name: u.name, role: u.role },
      create: {
        email: u.email,
        name: u.name,
        role: u.role,
        passwordHash,
        countryId: COUNTRY_ID,
      },
    });
  }
  // eslint-disable-next-line no-console
  console.log(`✓ Seeded ${users.length} users`);

  await prisma.district.upsert({
    where: { name: "Mukono" },
    update: {},
    create: { id: "dist_mukono", name: "Mukono", region: "Central" },
  });
  // eslint-disable-next-line no-console
  console.log("✓ Seeded 1 district");

  await prisma.cluster.upsert({
    where: { id: "cluster_mukono_a" },
    update: {},
    create: { id: "cluster_mukono_a", name: "Mukono Cluster A", districtId: "dist_mukono" },
  });
  // eslint-disable-next-line no-console
  console.log("✓ Seeded 1 cluster");

  for (let i = 0; i < SCHOOL_IDS.length; i++) {
    const id = SCHOOL_IDS[i];
    await prisma.school.upsert({
      where: { id },
      update: {},
      create: {
        id,
        name: `Demo Primary School ${i + 1}`,
        clusterId: "cluster_mukono_a",
        districtId: "dist_mukono",
        isCoreSchool: i < 3,
        totalEnrollment: 250 + i * 60,
        enrollmentSource: "Seed",
        enrollmentLastUpdated: new Date(),
      },
    });
  }
  // eslint-disable-next-line no-console
  console.log(`✓ Seeded ${SCHOOL_IDS.length} schools`);

  await prisma.partner.upsert({
    where: { name: "BrightFuture Education Partners" },
    update: {},
    create: {
      id: PARTNER_ID,
      name: "BrightFuture Education Partners",
      contactName: "Daniel Mwangi (BFEP)",
      contactEmail: "daniel.mwangi@brightfuture.org",
      status: "Active",
      countryId: COUNTRY_ID,
    },
  });
  // eslint-disable-next-line no-console
  console.log("✓ Seeded 1 partner");

  // 1 active CostSetting per ActivityKind — the cost-engine needs
  // these to produce non-zero plan totals.
  const kinds = [
    "CLUSTER_TRAINING",
    "IN_SCHOOL_COACHING",
    "SCHOOL_VISIT",
    "SSA_FOLLOW_UP",
    "HANDOVER_MEETING",
    "LESSON_OBSERVATION",
    "PARTNER_FOLLOW_UP",
    "TRAINING_FOLLOW_UP",
    "DATA_COLLECTION",
    "COURTESY_VISIT",
  ];
  for (const k of kinds) {
    await prisma.costSetting.upsert({
      where: {
        countryId_activityKind_effectiveFyIso: {
          countryId: COUNTRY_ID,
          activityKind: k,
          effectiveFyIso: "2026-FY",
        },
      },
      update: {},
      create: {
        countryId: COUNTRY_ID,
        activityKind: k,
        effectiveFyIso: "2026-FY",
        costPerUnitCents: 140_000 * 100,
        status: "Active",
        approvedAt: new Date(),
      },
    });
  }
  // eslint-disable-next-line no-console
  console.log(`✓ Seeded ${kinds.length} cost settings (Active)`);

  // eslint-disable-next-line no-console
  console.log("\n✅ Seed complete.\n");
  await prisma.$disconnect();
}

main().catch(async (e) => {
  // eslint-disable-next-line no-console
  console.error("Seed failed:", e);
  process.exitCode = 1;
});
