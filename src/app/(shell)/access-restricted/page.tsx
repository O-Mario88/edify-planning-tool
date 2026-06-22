import Link from "next/link";
import { ShieldX, ArrowRight } from "lucide-react";
import { PageHeader } from "@/components/ui/PageHeader";
import { getCurrentUser } from "@/lib/auth";
import { ROLE_REDIRECT } from "@/lib/auth-public";

// Shown when a signed-in user is bounced from a surface their role may not
// access (currently the operational School Directory). The middleware blocks
// the route before any data is fetched; this page just explains why and points
// the user back to where they CAN work.
export default async function AccessRestrictedPage({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const sp = await searchParams;
  const fromRaw = Array.isArray(sp.from) ? sp.from[0] : sp.from;
  const from = fromRaw ?? "";
  const user = await getCurrentUser();
  const home = ROLE_REDIRECT[user.role] ?? "/";
  const isDirectory = from.startsWith("/schools") || from.startsWith("/school-directory");
  const isFieldPlanning =
    from.startsWith("/planning") ||
    from.startsWith("/my-plan") ||
    from.startsWith("/completed-activities") ||
    from.startsWith("/trainings") ||
    from.startsWith("/visits");

  return (
    <>
      <PageHeader title="Access Restricted" noBack />
      <div className="px-4 sm:px-6 pt-4 pb-24 max-w-2xl mx-auto">
      <div className="card p-6 sm:p-8 text-center">
        <div className="mx-auto mb-4 grid place-items-center w-12 h-12 rounded-full bg-rose-50 border border-rose-200">
          <ShieldX size={22} className="text-rose-600" />
        </div>
        <h2 className="text-[18px] font-extrabold tracking-tight mb-1.5">Access restricted</h2>
        {isDirectory ? (
          <p className="text-[13px] text-slate-600 leading-relaxed mb-1">
            The <strong>School Directory</strong> is an operational working surface for the
            CCEO, Program Lead, and Impact Assessment roles. Your role
            ({user.role}) leads through analytics, reports, budget, and recruitment
            intelligence — not the operational school list.
          </p>
        ) : isFieldPlanning ? (
          <p className="text-[13px] text-slate-600 leading-relaxed mb-1">
            <strong>Field planning</strong> is an operational working surface for the
            CCEO and Program Lead roles. Your role ({user.role}) monitors execution
            through the dashboard, analytics, and finance — and can assign tickets
            to Program Leads from the director dashboard. Field planning is not
            part of your workflow.
          </p>
        ) : (
          <p className="text-[13px] text-slate-600 leading-relaxed mb-1">
            Your role ({user.role}) doesn’t have access to this page.
          </p>
        )}
        <p className="text-[12px] muted mb-5">
          {isFieldPlanning
            ? "No plan records were loaded. This restriction is enforced on both the page and the backend."
            : "No school records were loaded. This restriction is enforced on both the page and the backend."}
        </p>
        <div className="flex flex-wrap items-center justify-center gap-2">
          <Link href={home} className="inline-flex items-center gap-1.5 rounded-md bg-[var(--color-edify-primary)] text-white px-3.5 py-2 text-[12px] font-bold hover:opacity-90">
            Go to my dashboard <ArrowRight size={13} />
          </Link>
          {isDirectory && (
            <Link href="/analytics" className="inline-flex items-center gap-1.5 rounded-md border border-[var(--color-edify-border)] px-3.5 py-2 text-[12px] font-bold hover:bg-[var(--color-edify-soft)]/40">
              Open Analytics
            </Link>
          )}
        </div>
      </div>
      </div>
    </>
  );
}
