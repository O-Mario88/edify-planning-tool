import { getCurrentUser } from "@/lib/auth";
import { todayDataForRole } from "@/lib/today-mock";
import { TodayConsole } from "./TodayConsole";
import { isMockAllowed } from "@/lib/mock-policy";
import { PageHeader } from "@/components/ui/PageHeader";
import { TodayCommandCenter } from "@/components/command/TodayCommandCenter";

// Today's Tasks — role-scoped. Production renders the LIVE command-center feed
// (/api/command-center/today): the real, priority-ranked "what must I do next"
// for the signed-in user — due/overdue/waiting items, each with one action and
// a plain-language reason. Empty (all-caught-up) on a clean DB, populates as
// workflow records are created. The rich mock console renders in dev only.
export default async function TodayPage() {
  const user = await getCurrentUser();
  if (!isMockAllowed()) {
    return (
      <>
        <PageHeader title="Today" subtitle="The work waiting on you right now — ranked by urgency, each with one next action." />
        <div className="px-3 sm:px-4 md:px-5 pb-12 pt-3">
          <TodayCommandCenter />
        </div>
      </>
    );
  }
  const data = todayDataForRole(user.role);

  return (
    <TodayConsole
      data={data}
      userName={user.name}
      userInitials={user.initials}
    />
  );
}
