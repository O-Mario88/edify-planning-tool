import { LoginHeroSection } from "@/components/auth/LoginHeroSection";
import { LoginPanel } from "@/components/auth/LoginPanel";
import { getLoginHeroMetrics } from "@/lib/auth-metrics";

// /login
//
// Server component. Calls getLoginHeroMetrics() directly so the hero stats
// are available in the first paint and never fall back to client fetching
// from a flash-of-zero state. The same function powers the public
// /api/auth/login-metrics route.
// Always render fresh so the hero stats reflect the live database, not a
// build-time snapshot.
export const dynamic = "force-dynamic";

export default async function LoginPage() {
  const metrics = await getLoginHeroMetrics();
  return (
    <div className="grid grid-cols-1 md:grid-cols-[1.05fr_1fr] min-h-screen w-full">
      <LoginHeroSection metrics={metrics} />
      <LoginPanel />
    </div>
  );
}
