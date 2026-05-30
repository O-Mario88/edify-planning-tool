import { redirect } from "next/navigation";

// Catch-all for legacy `/m/*` bookmarks. Maps the old subpath to the new
// top-level route, then redirects. Anything we don't recognize falls
// back to /dashboard so the user lands somewhere useful.
const REWRITES: Record<string, string> = {
  "home":           "/dashboard",
  "schools":        "/schools",
  "plan":           "/my-plan",
  "plan/new":       "/plans/new",
  "route":          "/route",
  "queue":          "/queue",
  "today":          "/today",
  "more":           "/more",
  "cpl/team":       "/my-team",
  "cpl/approvals":  "/approvals",
  "cpl/targets":    "/my-targets",
};

export default async function LegacyMobileRedirect({
  params,
}: {
  params: Promise<{ legacy: string[] }>;
}) {
  const { legacy } = await params;
  const key = (legacy ?? []).join("/");
  redirect(REWRITES[key] ?? "/dashboard");
}
