import { StubPage } from "@/components/shell/StubPage";
import { readAuditLog } from "@/lib/actions/audit";
import { SeedSamplePlanButton } from "@/components/admin/SeedSamplePlanButton";

// Audit Log — the canonical read of `src/lib/actions/audit.ts`.
//
// Every Bucket-C server action emits an AuditEventRecord via emitAudit;
// this page reads them newest-first and renders them in the same row
// chrome as the static demo entries (so the page is still useful in a
// cold session). When the live store is populated, those rows display
// first; the static demo rows sit below as a "before this session"
// reference, so the page never looks empty.

type DemoEntry = {
  id: string;
  actor: string;
  action: string;
  target: string;
  ago: string;
  ip: string;
  tone: "edify" | "amber" | "rose";
};

const DEMO_ENTRIES: DemoEntry[] = [
  { id: "a-1", actor: "demo@edify.org",          action: "Logged in",                   target: "Web",                       ago: "12m", ip: "192.168.1.112", tone: "edify" },
  { id: "a-2", actor: "sarah.okello@edify.org",   action: "Approved fund request",       target: "FR fr1",                    ago: "1h",  ip: "192.168.1.112", tone: "edify" },
  { id: "a-3", actor: "daniel.mwangi@edify.org",  action: "Submitted daily debrief",     target: "DEB-STF-DM-014-20251112",   ago: "2h",  ip: "192.168.1.112", tone: "edify" },
  { id: "a-4", actor: "esther.wanjiru@edify.org", action: "Disbursed fund request",      target: "FR fr4",                    ago: "3h",  ip: "10.0.0.31",     tone: "edify" },
  { id: "a-5", actor: "admin@edify.org",          action: "Changed role assignment",     target: "anne.wairimu@edify.org → HumanResource", ago: "1d", ip: "10.0.0.7", tone: "amber" },
  { id: "a-6", actor: "paul.chinyama@edify.org",  action: "Failed sign-in attempt",      target: "Web (wrong password)",      ago: "2d",  ip: "192.168.1.112", tone: "rose" },
  { id: "a-7", actor: "system",                   action: "Auto-blocked planning",       target: "May 9 (public holiday)",    ago: "2d",  ip: "—",             tone: "edify" },
];

const TONE: Record<DemoEntry["tone"], string> = {
  edify: "bg-[var(--color-edify-soft)]/80 text-[var(--color-edify-primary)]",
  amber: "bg-amber-100  text-amber-700",
  rose:  "bg-rose-100   text-rose-700",
};

// Map a canonical action name to a UI tone. Anything that smells like
// a security event (login.failed, role.changed, override.*) shows in a
// warmer tone so it stands out at a glance.
function toneFor(action: string): DemoEntry["tone"] {
  if (action.includes("failed") || action.includes("rejected")) return "rose";
  if (action.includes("override") || action.includes("returned") || action.includes("adminClosed")) return "amber";
  return "edify";
}

// Render an ISO timestamp as a relative "ago" string. Lightweight so we
// don't ship Intl.RelativeTimeFormat for a page that scans seconds.
function relativeFrom(iso: string): string {
  const then = new Date(iso).getTime();
  if (!Number.isFinite(then)) return "—";
  const sec = Math.max(0, Math.floor((Date.now() - then) / 1000));
  if (sec < 5)       return "just now";
  if (sec < 60)      return `${sec}s`;
  if (sec < 3600)    return `${Math.floor(sec / 60)}m`;
  if (sec < 86400)   return `${Math.floor(sec / 3600)}h`;
  return `${Math.floor(sec / 86400)}d`;
}

// Don't cache — every request should reflect the latest mutations.
// revalidatePath in the actions also busts this; the export here is
// belt-and-braces for the Read path.
export const dynamic = "force-dynamic";

export default function AuditLogPage() {
  const live = readAuditLog({ limit: 100 });

  return (
    <StubPage
      title="Audit Log"
      subtitle={`Every privileged action is logged here for compliance. Sign-ins, role changes, fund approvals, planning overrides — all timestamped, with actor + IP. ${live.length > 0 ? `${live.length} live event${live.length === 1 ? "" : "s"} this session.` : "No live events yet."}`}
    >
      {/* Build-out aid: one-click run of the full W3 → W5 chain so the
          audit table and /notifications populate without manual UI
          stitching. Remove once the real plan-builder is wired. */}
      <section className="card rounded-2xl p-3.5 flex items-start gap-3">
        <div className="flex-1 min-w-0">
          <h2 className="text-body font-extrabold tracking-tight">Smoke-test the workflow</h2>
          <p className="text-caption muted mt-0.5">
            Runs createPlan → addActivityToPlan ×3 → submitPlan → approvePlan in sequence.
            Each step writes one audit row + at least one notification.
            Approval triggers W5 auto-generation of weekly fund requests.
          </p>
        </div>
        <SeedSamplePlanButton />
      </section>

      <section className="card rounded-2xl overflow-hidden">
        <table className="w-full text-[12px]">
          <thead className="bg-[var(--color-edify-soft)]/40">
            <tr className="text-[10px] muted font-bold uppercase tracking-wide">
              <th scope="col" className="text-left  px-4 py-2.5">When</th>
              <th scope="col" className="text-left  px-4 py-2.5">Actor</th>
              <th scope="col" className="text-left  px-4 py-2.5">Action</th>
              <th scope="col" className="text-left  px-4 py-2.5">Target</th>
              <th scope="col" className="text-left  px-4 py-2.5">IP</th>
            </tr>
          </thead>
          <tbody>
            {/* Live events — newest first */}
            {live.map((e) => {
              const tone = toneFor(e.action);
              return (
                <tr key={e.id} className="border-t border-[#eef2f4] bg-[var(--color-edify-soft)]/10">
                  <td className="px-4 py-2.5 muted tabular">{relativeFrom(e.createdAt)}</td>
                  <td className="px-4 py-2.5 font-semibold">
                    {e.actorName ?? e.actorId}
                    <span className="ml-1.5 text-[10px] muted font-semibold">· {e.actorRole}</span>
                  </td>
                  <td className="px-4 py-2.5">
                    <span className={`inline-flex items-center px-1.5 py-[2px] rounded-md text-[10px] font-extrabold ${TONE[tone]}`}>
                      {e.action}
                    </span>
                  </td>
                  <td className="px-4 py-2.5 font-mono text-[11px] muted">
                    {e.subjectKind}/{e.subjectId.slice(0, 16)}
                    {e.subjectId.length > 16 && "…"}
                  </td>
                  <td className="px-4 py-2.5 font-mono text-[11px] muted">live</td>
                </tr>
              );
            })}
            {/* Static demo events — page never looks empty before any
                action has fired in this session. */}
            {DEMO_ENTRIES.map((e) => (
              <tr key={e.id} className="border-t border-[#eef2f4]">
                <td className="px-4 py-2.5 muted">{e.ago}</td>
                <td className="px-4 py-2.5 font-semibold">{e.actor}</td>
                <td className="px-4 py-2.5">
                  <span className={`inline-flex items-center px-1.5 py-[2px] rounded-md text-[10px] font-extrabold ${TONE[e.tone]}`}>
                    {e.action}
                  </span>
                </td>
                <td className="px-4 py-2.5 font-mono text-[11px] muted">{e.target}</td>
                <td className="px-4 py-2.5 font-mono text-[11px] muted">{e.ip}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>
      <p className="text-caption muted">
        Audit retention: 365 days (data residency: Kenya, EAC). Filtered exports require dual-Admin sign-off.
      </p>
    </StubPage>
  );
}
