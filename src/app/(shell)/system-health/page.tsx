import { redirect } from "next/navigation";
import { getCurrentUser } from "@/lib/auth";
import { ROLE_REDIRECT } from "@/lib/auth-public";
import { SectionHeader } from "@/components/ui/SectionHeader";
import { MockLeakageCard } from "@/components/system-health/MockLeakageCard";

// System Health — production-safety + mock-data-leakage status (spec §18).
// Admin-only.
export default async function SystemHealthPage() {
  const user = await getCurrentUser();
  if (user.role !== "Admin") redirect(ROLE_REDIRECT[user.role] ?? "/");

  return (
    <div className="px-4 sm:px-6 pt-4 pb-24 space-y-4">
      <SectionHeader
        tier="strategic"
        eyebrow="System health"
        title="Production safety & mock-data status"
        description="Tracks the backend-only migration: which frontend pages and components still import mock data, and whether the app is configured to never render fake data in production."
      />
      <MockLeakageCard />
    </div>
  );
}
