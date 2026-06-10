// DashboardGreetingHero — the standalone greeting hero every dashboard
// renders DIRECTLY under the top page header.
//
// System-wide layout rule (spec): 1. Top header → 2. Greeting hero →
// 3. Statistics snapshot → 4. Main work content. The hero is the
// orientation surface ("Good morning, X" + role mission + today's
// one-sentence summary); it must come before any stats or work queues.
//
// This wraps the same MissionHeader + role-action-engine header that
// CommandStack used to render internally — pages now render this first
// and pass `hideMission` to CommandStack so the greeting never repeats.

import { cookies } from "next/headers";
import type { DemoUser } from "@/lib/auth";
import { buildRoleActionBoard } from "@/lib/actions/role-action-engine";
import { MissionHeader } from "@/components/actions/MissionHeader";

export async function DashboardGreetingHero({ user }: { user: DemoUser }) {
  const jar = await cookies();
  const cookieHeader = jar
    .getAll()
    .map((c) => `${c.name}=${c.value}`)
    .join("; ");
  const board = buildRoleActionBoard({
    role: user.role,
    name: user.name,
    email: user.email,
    cookieHeader,
  });
  return <MissionHeader header={board.header} />;
}
