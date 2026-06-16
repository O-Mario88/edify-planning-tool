// /messages — Inbox for every internal role (CCEO / PL / CD / RVP / HR / IA /
// Accountant / Admin). Backend-wired: <LiveInbox/> fetches /api/messages (the
// same GET the bell badge + drawer use) and lists the caller's received
// messages, each linking to /messages/[threadId] (the LiveThread reader). One
// live source of truth — the inbox, the bell, and the reader all show the same
// messages. No mock store; empty when the database has no inbox messages.

import Link from "next/link";
import { redirect } from "next/navigation";
import { PenSquare } from "lucide-react";
import { PageHeader } from "@/components/ui/PageHeader";
import { LiveInbox } from "@/components/messages/LiveInbox";
import { getCurrentUser } from "@/lib/auth";
import { ROLE_REDIRECT } from "@/lib/auth-public";

// Internal roles only — partners read their own surface at
// /partner/messages. Anyone outside this set bounces to their role's
// landing page.
const ALLOWED = new Set([
  "CCEO",
  "CountryProgramLead",
  "CountryDirector",
  "RVP",
  "HumanResource",
  "ProgramAccountant",
  "ImpactAssessment",
  "Admin",
]);

export default async function MessagesPage() {
  const user = await getCurrentUser();
  if (!ALLOWED.has(user.role)) redirect(ROLE_REDIRECT[user.role]);

  return (
    <>
      <PageHeader
        title="Messages"
        subtitle="Internal communication — feedback, decisions, debriefs routed to you, and program coordination. Stays in the app."
        backFallbackHref="/dashboard"
      />
      <div className="px-4 sm:px-5 lg:px-6 pt-2 pb-12 space-y-4">
        <div className="flex items-center justify-end gap-3">
          <Link
            href="/messages/new"
            className="inline-flex items-center gap-1.5 h-9 px-3.5 rounded-lg bg-[var(--color-edify-primary)] hover:bg-[var(--color-edify-dark)] text-white text-body font-extrabold shadow-[0_1px_2px_rgba(15,23,32,0.06)] whitespace-nowrap"
          >
            <PenSquare size={13} />
            New message
          </Link>
        </div>
        <LiveInbox />
      </div>
    </>
  );
}
