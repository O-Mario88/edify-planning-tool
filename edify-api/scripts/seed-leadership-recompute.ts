/**
 * Populate LeadershipDecisionInsight rows from live operational data.
 * Run after seed / migrate deploy so decision-engine surfaces are not empty.
 *
 *   npm run seed:leadership-recompute
 *   npm run seed:leadership-recompute -- 2026
 */
import { NestFactory } from '@nestjs/core';
import { AppModule } from '../src/app.module';
import { LeadershipEngineService } from '../src/modules/leadership/leadership-engine.service';
import { getOperationalFY } from '../src/common/fy/fy.util';

async function main() {
  const fy = process.argv[2] ?? getOperationalFY();
  const app = await NestFactory.createApplicationContext(AppModule, { logger: ['error', 'warn'] });
  try {
    const engine = app.get(LeadershipEngineService);
    const r = await engine.recompute(fy);
    console.log(`✓ Leadership recompute (FY ${fy}): ${r.generated} insight(s)`, r.boards);
  } finally {
    await app.close();
  }
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
