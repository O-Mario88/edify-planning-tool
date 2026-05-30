import { redirect } from "next/navigation";
// Legacy /m index — the mobile screens are now top-level routes
// (/today, /more, /route, /queue, /my-plan, /plans/new, /my-team,
// /approvals, /my-targets). Send users to the role-aware dashboard.
export default function MobileIndex() {
  redirect("/dashboard");
}
