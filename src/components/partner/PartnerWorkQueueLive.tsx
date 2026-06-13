// PartnerWorkQueueLive — the partner's OWN assigned activities, straight from
// the backend. This is the round-trip: when a CCEO/PL assigns an activity to a
// partner (Activity.assignedPartnerId), it lands here in that partner's session.
// The field officer authenticates as the partner user linked to the Partner org,
// so they see only their org's work. Renders nothing when the backend is off.

import { Handshake, School2, CalendarClock, ClipboardCheck, CircleAlert } from "lucide-react";
import { getCurrentUser } from "@/lib/auth";
import { fetchMyPartnerActivities } from "@/lib/api/surfaces";

const STATUS_TONE: Record<string, string> = {
  completed: "bg-emerald-100 text-emerald-700",
  ia_verified: "bg-emerald-100 text-emerald-700",
  paid: "bg-emerald-100 text-emerald-700",
  in_progress: "bg-sky-100 text-sky-700",
  evidence_uploaded: "bg-sky-100 text-sky-700",
  awaiting_ia_verification: "bg-amber-100 text-amber-700",
  planned: "bg-violet-100 text-violet-700",
  scheduled: "bg-violet-100 text-violet-700",
  partner_scheduled: "bg-violet-100 text-violet-700",
  assigned_to_partner: "bg-amber-100 text-amber-700",
};

function fmtType(t: string): string {
  return t.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}
function fmtDate(iso: string | null): string {
  if (!iso) return "Unscheduled";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? "—" : d.toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

export async function PartnerWorkQueueLive({ limit = 12 }: { limit?: number }) {
  const user = await getCurrentUser();
  const r = await fetchMyPartnerActivities(user);
  if (!r.live) return null;
  const { partner, counts, activities } = r.data;

  const tiles = [
    { label: "Assigned to us", value: counts.total, Icon: ClipboardCheck },
    { label: "Open", value: counts.open, Icon: CircleAlert, alert: counts.open > 0 },
    { label: "Scheduled", value: counts.scheduled, Icon: CalendarClock },
    { label: "Awaiting evidence", value: counts.awaitingEvidence, Icon: School2, alert: counts.awaitingEvidence > 0 },
  ];

  return (
    <section className="card p-3.5">
      <header className="flex items-center justify-between gap-2 mb-3 flex-wrap">
        <div>
          <h3 className="text-[13px] font-extrabold tracking-tight inline-flex items-center gap-1.5">
            <Handshake size={14} className="text-[var(--color-edify-primary)]" /> Assigned to {partner.name}
          </h3>
          <p className="text-[11.5px] muted">Activities routed to your organization by program staff.</p>
        </div>
        <span className="inline-flex items-center gap-1 rounded-full bg-[var(--color-edify-soft)] text-[var(--color-edify-primary)] px-2 py-0.5 text-[10px] font-bold border border-[var(--color-edify-border)]">Live · backend</span>
      </header>

      <div className="grid grid-cols-2 sm:grid-cols-4 gap-2.5 mb-3">
        {tiles.map((t) => (
          <div key={t.label} className="rounded-lg border border-[var(--color-edify-divider)] p-2.5">
            <div className="text-[10px] font-semibold muted leading-tight inline-flex items-center gap-1">
              <t.Icon size={10} className={t.alert ? "text-rose-500" : "text-[var(--color-edify-primary)]"} /> {t.label}
            </div>
            <div className={`text-[20px] font-extrabold tabular leading-none mt-1 ${t.alert ? "text-rose-600" : ""}`}>{t.value}</div>
          </div>
        ))}
      </div>

      {activities.length === 0 ? (
        <p className="text-[12px] muted py-3 text-center">No activities assigned to your organization yet.</p>
      ) : (
        <ul className="divide-y divide-[var(--color-edify-divider)]">
          {activities.slice(0, limit).map((a) => (
            <li key={a.id} className="py-2.5 flex items-center gap-3">
              <span className="h-9 w-9 rounded-md bg-[var(--color-edify-soft)]/80 text-[var(--color-edify-primary)] grid place-items-center shrink-0">
                <School2 size={14} />
              </span>
              <div className="flex-1 min-w-0">
                <div className="text-body font-extrabold tracking-tight truncate">{a.schoolName ?? "—"}</div>
                <div className="text-caption muted truncate">{fmtType(a.activityType)}{a.district ? ` · ${a.district}` : ""} · {fmtDate(a.scheduledDate)}</div>
              </div>
              <span className={`inline-flex items-center px-1.5 py-[2px] rounded-md text-[10px] font-extrabold whitespace-nowrap capitalize ${STATUS_TONE[a.status] ?? "bg-[var(--color-edify-soft)]"}`}>
                {a.status.replace(/_/g, " ")}
              </span>
            </li>
          ))}
        </ul>
      )}
      {activities.length > limit && <p className="text-[11px] muted mt-2">Showing {limit} of {activities.length} assigned activities.</p>}
    </section>
  );
}
