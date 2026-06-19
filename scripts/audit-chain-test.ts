// R1 + R2 proof on a CLEAN chain: the ported AuditService (Prisma 7 + PrismaPg
// adapter) must (R1) write+recompute a byte-consistent hash chain and (R2)
// serialize concurrent appends via the pg advisory lock so the chain stays
// strictly linear. Run against a THROWAWAY DB:
//   DATABASE_URL=<scratch> npx tsx scripts/audit-chain-test.ts
import { prisma } from "../src/server/prisma/prisma.service";
import { AuditService } from "../src/server/common/audit/audit.service";

async function main() {
  const audit = new AuditService(prisma);
  const N = 25;

  // Fire N appends CONCURRENTLY — without the advisory lock these would race
  // and corrupt prevHash linkage.
  await Promise.all(
    Array.from({ length: N }, (_, i) =>
      audit.log({
        action: "consolidation.test",
        subjectKind: "test",
        subjectId: `row-${i}`,
        payload: { i, nested: { b: 2, a: 1 }, list: [3, 1, 2] },
      }),
    ),
  );

  const chain = await audit.verifyChain();
  console.log("verifyChain:", JSON.stringify(chain));
  if (!chain.ok) throw new Error(`R1/R2 FAILED — chain broke at seq ${chain.brokenAtSeq} (${chain.reason})`);
  if (chain.checked < N) throw new Error(`expected >= ${N} chained rows, got ${chain.checked}`);

  await prisma.$disconnect();
  console.log(`\n✅ R1+R2 passed: ${chain.checked} concurrent audit appends form a valid hash chain under Prisma 7 + PrismaPg`);
}

main().catch((e) => { console.error("❌", e); process.exit(1); });
