import Link from "next/link";
import { ChevronDown, KeyRound, Pencil } from "lucide-react";
import { StubPage } from "@/components/shell/StubPage";
import { SectionCard, StatusBadge } from "@/components/ui/primitives";
import { ProfilePhotoEditor } from "@/components/profile/ProfilePhotoEditor";
import { getCurrentUser } from "@/lib/auth";
import type { EdifyRole } from "@/lib/auth";

// Human-readable role labels. Mirrors SUBTITLE_BY_ROLE but trims the
// "Console" suffix so the row reads as a job title rather than a screen
// name. Keep this local until the canonical ROLE_LABEL lands in
// auth-public.ts.
const ROLE_LABEL: Record<EdifyRole, string> = {
  CCEO:                "Core Schools Officer (CCEO)",
  CountryProgramLead:  "Country Program Lead",
  CountryDirector:     "Country Director",
  RVP:                 "Regional Vice President",
  ProgramAccountant:   "Program Accountant",
  ImpactAssessment:    "M&E / Impact Assessment",
  HumanResource:       "Human Resource",
  Admin:               "Administrator",
  PartnerAdmin:        "Partner Admin",
  PartnerFieldOfficer: "Partner Field Officer",
  PartnerViewer:       "Partner Viewer",
};

export default async function ProfilePage() {
  const user = await getCurrentUser();

  return (
    <StubPage
      title="Profile"
      subtitle="Your Edify identity and account preferences."
    >
      {/* Hero block — upload/replace/remove your headshot (every role). */}
      <section className="card p-3.5 flex items-center gap-4">
        <ProfilePhotoEditor staffId={user.staffId} name={user.name} initials={user.initials} />
        <div className="flex-1 min-w-0">
          <div className="text-[18px] font-extrabold tracking-tight truncate">{user.name}</div>
          <div className="text-body muted truncate">{ROLE_LABEL[user.role]}</div>
          <div className="text-[11.5px] muted truncate">{user.email}</div>
        </div>
        <StatusBadge tone="green">Active</StatusBadge>
      </section>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {/* About you */}
        <SectionCard
          title="About you"
          subtitle="Information your team and country admin can see."
        >
          <div className="divide-y divide-[var(--color-edify-divider)]">
            <Row term="Name" value={user.name} />
            <Row term="Role" value={ROLE_LABEL[user.role]} />
            <Row term="Country" value="Uganda" />
            <Row term="Team" value="Program Lead: TBD" />
            <Row term="Email" value={user.email} />
            <Row
              term="Status"
              value={<StatusBadge tone="green">Active</StatusBadge>}
            />
          </div>
        </SectionCard>

        {/* Account actions */}
        <SectionCard
          title="Account actions"
          subtitle="Manage how you sign in to Edify."
        >
          <div className="divide-y divide-[var(--color-edify-divider)]">
            <Link
              href="/reset-password"
              className="flex items-center gap-3 py-2.5 -mx-1 px-1 rounded-lg hover:bg-[var(--color-edify-soft)]/40"
            >
              <span className="h-8 w-8 rounded-md bg-[var(--color-edify-soft)]/80 text-[var(--color-edify-primary)] grid place-items-center shrink-0">
                <KeyRound size={14} />
              </span>
              <div className="flex-1 min-w-0">
                <div className="text-body font-semibold">Reset password</div>
                <div className="text-[11px] muted">Set a new password using a one-time link</div>
              </div>
            </Link>
            <div className="flex items-center gap-3 py-2.5">
              <span className="h-8 w-8 rounded-md bg-[#f3f4f6] text-[var(--color-edify-muted)] grid place-items-center shrink-0">
                <Pencil size={14} />
              </span>
              <div className="flex-1 min-w-0">
                <div className="text-body font-semibold">Edit Profile</div>
                <div className="text-[11px] muted leading-snug">
                  Edit access provisioned by Country Admin.
                </div>
              </div>
              <button
                type="button"
                disabled
                className="h-7 px-2.5 rounded-md border border-[var(--color-edify-border)] text-[var(--color-edify-muted)] text-[11.5px] font-semibold cursor-not-allowed"
              >
                Edit
              </button>
            </div>
          </div>
        </SectionCard>
      </div>

      {/* Developer details — raw IDs live here, not in primary content */}
      <details className="card rounded-2xl px-4 py-3 group">
        <summary className="flex items-center justify-between gap-3 cursor-pointer list-none">
          <div className="min-w-0">
            <div className="text-[13px] font-extrabold tracking-tight">Developer details</div>
            <div className="text-[11.5px] muted">Internal identifiers used by Salesforce and the audit log.</div>
          </div>
          <ChevronDown
            size={16}
            className="text-[var(--color-edify-muted)] shrink-0 transition-transform group-open:rotate-180"
          />
        </summary>
        <div className="mt-3 grid grid-cols-1 sm:grid-cols-3 gap-3 text-[12px]">
          <DevField term="Staff ID" value={user.staffId} />
          <DevField term="Salesforce Owner ID" value={user.salesforceOwnerId} />
          <DevField term="App Role" value={user.appRole} />
        </div>
      </details>
    </StubPage>
  );
}

function Row({ term, value }: { term: string; value: React.ReactNode }) {
  return (
    <div className="flex items-center justify-between gap-3 py-2.5">
      <div className="text-[11.5px] muted font-semibold">{term}</div>
      <div className="text-body font-semibold text-right truncate max-w-[60%]">{value}</div>
    </div>
  );
}

function DevField({ term, value }: { term: string; value: string }) {
  return (
    <div>
      <div className="text-caption muted font-bold tracking-wide uppercase">{term}</div>
      <div className="font-extrabold tabular truncate">{value}</div>
    </div>
  );
}
