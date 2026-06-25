// ClusterIntelligencePanel — the open-ended Cluster Planning Intelligence
// view for the cluster detail page. Replaces the legacy "1st/2nd/3rd
// meeting" planning summary with:
//
//   • Recommendation card (focus intervention + reason + schedule CTA)
//   • SSA intervention performance (8 cards w/ delta + status)
//   • Improved / Declined intervention strips
//   • Coverage breakdown (not visited / not trained / neither)
//   • Cluster cadence summary (meetings/trainings this FY, last meeting)
//   • Schools in cluster list
//   • Previous meetings & trainings — unlimited history
//
// Pure server component that takes pre-computed `ClusterIntelligence`. The
// page renders this beside `ClusterProfileView` so the existing lifecycle
// queues + feedback panels remain available.

import Link from "next/link";
import {
  AlertTriangle, ArrowRight, Calendar, CheckCircle2, GraduationCap,
  MapPin, Sparkles, TrendingDown, TrendingUp, Users,
} from "lucide-react";
import { cn } from "@/lib/utils";
import {
  CLUSTER_GAP_CATEGORY_LABEL,
  type ClusterIntelligence,
  type InterventionPerformance,
  type SsaStatus,
} from "@/lib/cluster/cluster-intelligence";

type Props = {
  /** Cluster header (name + geography + ownership). */
  header: {
    id: string;
    name: string;
    district?: string | null;
    subCounties?: string[];
    region?: string | null;
    type?: string | null;
    cceoName?: string | null;
    plName?: string | null;
    partnerName?: string | null;
  };
  /** Pre-computed intelligence object (from `computeClusterIntelligence`). */
  intel: ClusterIntelligence;
  /** Optional unlimited activity history — each row carries enough context
   *  to render a meeting/training summary card. */
  history?: Array<{
    id: string;
    title: string;
    type: "meeting" | "training" | "sit" | "follow_up" | "project_session";
    date: string;
    focus?: string;
    attendance?: number;
    teachersTrained?: number;
    schoolLeadersTrained?: number;
    evidenceStatus?: string;
    activityCode?: string;
    iaStatus?: string;
    resolutions?: string;
    nextActions?: string;
  }>;
  /** Schools-in-cluster rows for the school list section. */
  schools?: Array<{
    schoolId: string;
    schoolName: string;
    schoolType: "Client" | "Core" | "Potential Core";
    accountOwner?: string;
    ssaStatus: "complete" | "missing" | "pending";
    latestSsa?: number;
    weakestIntervention?: string;
    visitStatus: "visited" | "not_visited";
    trainingStatus: "trained" | "not_trained";
    partnerSupportName?: string;
    projectAssignmentName?: string;
  }>;
  /** When the viewer can schedule activities, point the CTAs here. */
  scheduleHref?: string;
};

const STATUS_TONE: Record<SsaStatus, { bg: string; text: string; border: string }> = {
  Critical:        { bg: "bg-rose-50",    text: "text-rose-700",    border: "border-rose-200"   },
  "Needs Support": { bg: "bg-amber-50",   text: "text-amber-700",   border: "border-amber-200"  },
  Good:            { bg: "bg-emerald-50", text: "text-emerald-700", border: "border-emerald-200"},
  Strong:          { bg: "bg-emerald-50", text: "text-emerald-800", border: "border-emerald-300"},
};

function StatusPill({ status }: { status: SsaStatus }) {
  const tone = STATUS_TONE[status];
  return (
    <span className={cn("inline-flex items-center gap-1 px-1.5 py-[2px] rounded-md text-[10px] font-extrabold border", tone.bg, tone.text, tone.border)}>
      {status}
    </span>
  );
}

export function ClusterIntelligencePanel({ header, intel, history = [], schools = [], scheduleHref }: Props) {
  const { coverage, cadence, recommendation, ssaPerformance, improved, declined, averageSsaScore, weakestIntervention, strongestIntervention } = intel;

  return (
    <div className="space-y-3">
      {/* ── Section 1: Cluster Decision Summary ─────────────────────── */}
      <section className="card p-4 border border-[var(--color-edify-divider)]">
        <div className="flex items-start justify-between gap-3 flex-wrap">
          <div className="min-w-0">
            <div className="text-[11px] uppercase tracking-widest font-bold muted">Recommended Focus</div>
            <h2 className="text-[18px] font-extrabold tracking-tight mt-0.5">{recommendation.headline}</h2>
            <p className="text-[12px] text-[var(--color-edify-text)] leading-snug mt-1.5 max-w-xl">{recommendation.reason}</p>
            <div className="flex items-center gap-2 mt-2.5 flex-wrap">
              <span className="inline-flex items-center gap-1 px-2 py-[3px] rounded-md text-[10px] font-extrabold border border-[var(--color-edify-divider)] text-[var(--color-edify-muted)]">
                {CLUSTER_GAP_CATEGORY_LABEL[intel.gapCategory]}
              </span>
              {recommendation.focusIntervention && (
                <span className="inline-flex items-center gap-1 px-2 py-[3px] rounded-md text-[10px] font-extrabold bg-[var(--color-edify-soft)] text-[var(--color-edify-text)]">
                  Focus · {recommendation.focusIntervention}
                </span>
              )}
              <span className="inline-flex items-center gap-1 px-2 py-[3px] rounded-md text-[10px] font-extrabold bg-[var(--color-edify-soft)] text-[var(--color-edify-text)]">
                {recommendation.schoolsAffected} school{recommendation.schoolsAffected === 1 ? "" : "s"} affected
              </span>
            </div>
          </div>
          {scheduleHref && recommendation.priority !== "on_track" && (
            <Link
              href={scheduleHref}
              className="inline-flex items-center gap-1 h-10 px-4 rounded-md bg-[var(--color-edify-primary)] text-white text-[12px] font-extrabold hover:bg-[var(--color-edify-dark)] whitespace-nowrap"
            >
              {recommendation.suggestedActivityLabel}
              <ArrowRight size={14} />
            </Link>
          )}
        </div>

        {/* Quick cluster KPIs */}
        <div className="mt-4 grid grid-cols-2 sm:grid-cols-4 gap-2 text-[11px]">
          <KpiCell label="Schools" value={`${coverage.total}`} sub={`${coverage.client} client · ${coverage.core} core`} />
          <KpiCell label="Meetings this FY" value={`${cadence.meetingsThisFy}`} sub={cadence.lastMeetingDate ? `Last ${cadence.lastMeetingDate}` : "No meetings yet"} />
          <KpiCell label="Trainings this FY" value={`${cadence.trainingsThisFy}`} sub={cadence.teachersTrained > 0 ? `${cadence.teachersTrained} teachers trained` : "—"} />
          <KpiCell label="SSA average" value={averageSsaScore.toFixed(1)} sub={weakestIntervention ? `Weakest · ${weakestIntervention.intervention}` : "—"} tone={averageSsaScore >= 7 ? "good" : averageSsaScore >= 5 ? "warn" : "danger"} />
        </div>

        {/* Cadence alert strip */}
        <div className="mt-3 flex items-center flex-wrap gap-2">
          {!cadence.metThisQuarter && cadence.meetingsThisFy > 0 && (
            <FlagChip tone="warn" Icon={Calendar} label="Not met this quarter" />
          )}
          {cadence.meetingsThisFy === 0 && (
            <FlagChip tone="danger" Icon={AlertTriangle} label="No meetings this FY" />
          )}
          {coverage.neitherVisitNorTraining.length > 0 && (
            <FlagChip tone="danger" Icon={AlertTriangle} label={`${coverage.neitherVisitNorTraining.length} schools with neither visit nor training`} />
          )}
          {cadence.nextScheduledDate && (
            <FlagChip tone="info" Icon={Calendar} label={`Next scheduled · ${cadence.nextScheduledDate}`} />
          )}
        </div>
      </section>

      {/* ── Cluster header strip (geography + leadership) ──────────── */}
      <section className="card p-3 border border-[var(--color-edify-divider)]">
        <div className="text-[11px] uppercase tracking-widest font-bold muted">Cluster</div>
        <div className="flex items-start justify-between gap-3 flex-wrap mt-1">
          <div>
            <div className="text-[16px] font-extrabold tracking-tight">{header.name}</div>
            <div className="text-[11px] muted mt-0.5 inline-flex items-center gap-1.5">
              <MapPin size={11} />
              {[header.region, header.district, (header.subCounties ?? []).join(", ")].filter(Boolean).join(" · ")}
            </div>
          </div>
          <div className="text-[11px] muted text-right space-y-0.5">
            {header.cceoName && <div>CCEO · <span className="font-semibold text-[var(--color-edify-text)]">{header.cceoName}</span></div>}
            {header.plName && <div>PL · <span className="font-semibold text-[var(--color-edify-text)]">{header.plName}</span></div>}
            {header.partnerName && <div>Partner · <span className="font-semibold text-[var(--color-edify-text)]">{header.partnerName}</span></div>}
            {header.type && <div className="inline-flex items-center gap-1 px-1.5 py-[2px] rounded-md text-[10px] font-extrabold bg-[var(--color-edify-soft)] text-[var(--color-edify-text)]">{header.type}</div>}
          </div>
        </div>
      </section>

      {/* ── Section 2: SSA Intervention Performance ─────────────────── */}
      <section className="card p-3.5 border border-[var(--color-edify-divider)]">
        <header className="flex items-baseline justify-between gap-3 flex-wrap">
          <div>
            <h3 className="text-[14px] font-extrabold tracking-tight">SSA Intervention Performance</h3>
            <p className="text-[11px] muted mt-0.5">Average across {coverage.withCurrentFySsa} of {coverage.total} schools with current-FY SSA. {coverage.missingSsa > 0 ? `${coverage.missingSsa} school${coverage.missingSsa === 1 ? "" : "s"} missing SSA.` : "All schools have SSA."}</p>
          </div>
          {strongestIntervention && weakestIntervention && (
            <div className="text-[11px] muted">
              Strongest · <span className="font-semibold text-emerald-700">{strongestIntervention.intervention} {strongestIntervention.averageScore.toFixed(1)}</span>
              <span className="mx-1.5">·</span>
              Weakest · <span className="font-semibold text-rose-700">{weakestIntervention.intervention} {weakestIntervention.averageScore.toFixed(1)}</span>
            </div>
          )}
        </header>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-2 mt-3">
          {ssaPerformance.map((p) => <InterventionCard key={p.intervention} p={p} />)}
        </div>
      </section>

      {/* ── Improvement + Decline strips ───────────────────────────── */}
      {(improved.length > 0 || declined.length > 0) && (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
          {improved.length > 0 && (
            <section className="card p-3.5 border border-emerald-200 bg-emerald-50/40">
              <h3 className="text-[13px] font-extrabold tracking-tight inline-flex items-center gap-1.5">
                <TrendingUp size={12} className="text-emerald-700" /> SSA Improvement
              </h3>
              <ul className="mt-2 divide-y divide-emerald-200/60">
                {improved.map((i) => (
                  <li key={i.intervention} className="py-1.5 flex items-center justify-between gap-2">
                    <div className="min-w-0">
                      <div className="text-[12px] font-extrabold truncate">{i.intervention}</div>
                      <div className="text-[10px] muted">From {i.previousAverage.toFixed(1)} → {i.latestAverage.toFixed(1)} · {i.schoolsImproved} school{i.schoolsImproved === 1 ? "" : "s"} improved</div>
                    </div>
                    <div className="text-[12px] font-extrabold text-emerald-700">+{i.improvement.toFixed(1)}</div>
                  </li>
                ))}
              </ul>
            </section>
          )}
          {declined.length > 0 && (
            <section className="card p-3.5 border border-rose-200 bg-rose-50/40">
              <h3 className="text-[13px] font-extrabold tracking-tight inline-flex items-center gap-1.5">
                <TrendingDown size={12} className="text-rose-700" /> SSA Performance Drop
              </h3>
              <ul className="mt-2 divide-y divide-rose-200/60">
                {declined.map((d) => (
                  <li key={d.intervention} className="py-1.5">
                    <div className="flex items-center justify-between gap-2">
                      <div className="min-w-0">
                        <div className="text-[12px] font-extrabold truncate">{d.intervention}</div>
                        <div className="text-[10px] muted">From {d.previousAverage.toFixed(1)} → {d.latestAverage.toFixed(1)} · {d.schoolsDeclined} school{d.schoolsDeclined === 1 ? "" : "s"} declined</div>
                      </div>
                      <div className="text-[12px] font-extrabold text-rose-700">−{d.drop.toFixed(1)}</div>
                    </div>
                    <div className="text-[10px] muted mt-1">{d.recommendedResponse}</div>
                  </li>
                ))}
              </ul>
            </section>
          )}
        </div>
      )}

      {/* ── Section 3: School Coverage ─────────────────────────────── */}
      <section className="card p-3.5 border border-[var(--color-edify-divider)]">
        <h3 className="text-[13px] font-extrabold tracking-tight">School Coverage</h3>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-2 mt-3">
          <CoverageCell label="Not visited" count={coverage.notVisited.length} total={coverage.total} tone="warn" />
          <CoverageCell label="Not trained" count={coverage.notTrained.length} total={coverage.total} tone="warn" />
          <CoverageCell label="Neither visit nor training" count={coverage.neitherVisitNorTraining.length} total={coverage.total} tone="danger" priority />
          <CoverageCell label="Missing SSA" count={coverage.missingSsa} total={coverage.total} tone="info" />
        </div>
        {coverage.neitherVisitNorTraining.length > 0 && (
          <div className="mt-3 rounded-md border border-rose-200 bg-rose-50/40 p-2.5">
            <div className="text-[11px] uppercase tracking-wider font-bold text-rose-700">Priority schools — neither visit nor training</div>
            <ul className="mt-1.5 grid grid-cols-1 sm:grid-cols-2 gap-x-3 gap-y-1">
              {coverage.neitherVisitNorTraining.slice(0, 10).map((s) => (
                <li key={s.schoolId} className="text-[11.5px] text-[var(--color-edify-text)] truncate">
                  {s.schoolName} <span className="muted">· {s.schoolType}</span>
                </li>
              ))}
            </ul>
            {coverage.neitherVisitNorTraining.length > 10 && (
              <div className="text-[10px] muted mt-1">+{coverage.neitherVisitNorTraining.length - 10} more</div>
            )}
          </div>
        )}
      </section>

      {/* ── Section 4: Schools in Cluster ──────────────────────────── */}
      {schools.length > 0 && (
        <section className="card p-3.5 border border-[var(--color-edify-divider)]">
          <header className="flex items-center justify-between gap-3">
            <h3 className="text-[13px] font-extrabold tracking-tight inline-flex items-center gap-1.5">
              <Users size={12} /> Schools in Cluster <span className="muted font-bold text-[11px]">· {schools.length}</span>
            </h3>
          </header>
          <div className="mt-2 overflow-x-auto">
            <table className="min-w-full text-[11.5px]">
              <thead className="text-[10px] uppercase tracking-wider muted">
                <tr className="border-b border-[var(--color-edify-divider)]">
                  <th className="text-left py-1.5 pr-2 font-bold">School</th>
                  <th className="text-left py-1.5 pr-2 font-bold">Type</th>
                  <th className="text-left py-1.5 pr-2 font-bold">SSA</th>
                  <th className="text-left py-1.5 pr-2 font-bold">Latest</th>
                  <th className="text-left py-1.5 pr-2 font-bold">Weakest</th>
                  <th className="text-left py-1.5 pr-2 font-bold">Visit</th>
                  <th className="text-left py-1.5 pr-2 font-bold">Training</th>
                  <th className="text-left py-1.5 pr-2 font-bold">Partner</th>
                </tr>
              </thead>
              <tbody>
                {schools.map((s) => (
                  <tr key={s.schoolId} className="border-b border-[var(--color-edify-divider)] last:border-b-0">
                    <td className="py-1.5 pr-2 font-extrabold">
                      <Link href={`/schools/${encodeURIComponent(s.schoolId)}`} className="hover:underline">{s.schoolName}</Link>
                    </td>
                    <td className="py-1.5 pr-2">{s.schoolType}</td>
                    <td className="py-1.5 pr-2">{s.ssaStatus === "complete" ? <span className="text-emerald-700 font-bold">Done</span> : <span className="text-rose-700 font-bold">Missing</span>}</td>
                    <td className="py-1.5 pr-2 tabular">{s.latestSsa !== undefined ? s.latestSsa.toFixed(1) : "—"}</td>
                    <td className="py-1.5 pr-2 truncate max-w-[160px]">{s.weakestIntervention ?? "—"}</td>
                    <td className="py-1.5 pr-2">{s.visitStatus === "visited" ? <CheckCircle2 size={11} className="text-emerald-600 inline-block" /> : <span className="text-rose-700 text-[10px] font-extrabold">No</span>}</td>
                    <td className="py-1.5 pr-2">{s.trainingStatus === "trained" ? <CheckCircle2 size={11} className="text-emerald-600 inline-block" /> : <span className="text-rose-700 text-[10px] font-extrabold">No</span>}</td>
                    <td className="py-1.5 pr-2 truncate max-w-[140px]">{s.partnerSupportName ?? "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}

      {/* ── Section 5: Previous Meetings & Trainings — unlimited ──── */}
      <section className="card p-3.5 border border-[var(--color-edify-divider)]">
        <header className="flex items-center justify-between gap-3">
          <h3 className="text-[13px] font-extrabold tracking-tight inline-flex items-center gap-1.5">
            <GraduationCap size={12} /> Previous Cluster Activities <span className="muted font-bold text-[11px]">· {history.length}</span>
          </h3>
          {scheduleHref && (
            <Link href={scheduleHref} className="text-[11px] font-extrabold text-[var(--color-edify-primary)] inline-flex items-center gap-1 hover:underline">
              Schedule Cluster Activity <ArrowRight size={11} />
            </Link>
          )}
        </header>
        {history.length === 0 ? (
          <div className="mt-2 text-[12px] muted">No previous cluster activities recorded. Schedule the first cluster meeting or training to establish the planning rhythm.</div>
        ) : (
          <ul className="mt-2 divide-y divide-[var(--color-edify-divider)]">
            {history.map((h) => (
              <li key={h.id} className="py-2 grid grid-cols-12 gap-2 items-start">
                <div className="col-span-12 md:col-span-7 min-w-0">
                  <div className="text-[12px] font-extrabold truncate">{h.title}</div>
                  <div className="text-[10.5px] muted mt-0.5 inline-flex items-center gap-1.5">
                    <Calendar size={9} /> {h.date}
                    {h.focus && <span>· Focus {h.focus}</span>}
                    {h.activityCode && <span>· {h.activityCode}</span>}
                  </div>
                  {(h.resolutions || h.nextActions) && (
                    <div className="text-[11px] text-[var(--color-edify-text)] mt-1 line-clamp-2">
                      {h.resolutions ?? h.nextActions}
                    </div>
                  )}
                </div>
                <div className="col-span-12 md:col-span-5 text-[10.5px] flex flex-wrap items-center gap-1.5 md:justify-end">
                  {h.attendance !== undefined && (
                    <span className="px-1.5 py-[2px] rounded bg-[var(--color-edify-soft)] font-bold">{h.attendance} attendees</span>
                  )}
                  {h.teachersTrained !== undefined && h.teachersTrained > 0 && (
                    <span className="px-1.5 py-[2px] rounded bg-[var(--color-edify-soft)] font-bold">{h.teachersTrained} teachers</span>
                  )}
                  {h.schoolLeadersTrained !== undefined && h.schoolLeadersTrained > 0 && (
                    <span className="px-1.5 py-[2px] rounded bg-[var(--color-edify-soft)] font-bold">{h.schoolLeadersTrained} leaders</span>
                  )}
                  {h.evidenceStatus && (
                    <span className={cn("px-1.5 py-[2px] rounded font-bold",
                      h.evidenceStatus === "complete" || h.evidenceStatus === "verified" ? "bg-emerald-50 text-emerald-700" : "bg-amber-50 text-amber-700",
                    )}>{h.evidenceStatus}</span>
                  )}
                  {h.iaStatus && (
                    <span className={cn("px-1.5 py-[2px] rounded font-bold",
                      h.iaStatus === "verified" || h.iaStatus === "confirmed" ? "bg-emerald-50 text-emerald-700" : "bg-sky-50 text-sky-700",
                    )}>IA · {h.iaStatus}</span>
                  )}
                </div>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}

function KpiCell({ label, value, sub, tone = "default" }: { label: string; value: string; sub?: string; tone?: "default" | "good" | "warn" | "danger" }) {
  const toneClass =
    tone === "danger" ? "border-rose-200 bg-rose-50/40" :
    tone === "warn"   ? "border-amber-200 bg-amber-50/40" :
    tone === "good"   ? "border-emerald-200 bg-emerald-50/40" :
                        "border-[var(--color-edify-divider)]";
  return (
    <div className={cn("rounded-md border px-2.5 py-1.5", toneClass)}>
      <div className="text-[10px] uppercase tracking-wider font-bold muted">{label}</div>
      <div className="text-[15px] font-extrabold leading-tight">{value}</div>
      {sub && <div className="text-[10px] muted truncate">{sub}</div>}
    </div>
  );
}

function CoverageCell({ label, count, total, tone, priority }: { label: string; count: number; total: number; tone: "warn" | "danger" | "info"; priority?: boolean }) {
  const toneClass =
    tone === "danger" ? "border-rose-200 bg-rose-50/40 text-rose-700" :
    tone === "warn"   ? "border-amber-200 bg-amber-50/40 text-amber-700" :
                        "border-sky-200 bg-sky-50/40 text-sky-700";
  return (
    <div className={cn("rounded-md border px-2.5 py-1.5", toneClass)}>
      <div className="text-[10px] uppercase tracking-wider font-bold opacity-80 inline-flex items-center gap-1">
        {label} {priority && <Sparkles size={9} className="opacity-80" />}
      </div>
      <div className="text-[16px] font-extrabold leading-tight tabular">{count}<span className="text-[11px] opacity-60"> / {total}</span></div>
    </div>
  );
}

function FlagChip({ tone, Icon, label }: { tone: "warn" | "danger" | "info"; Icon: typeof Calendar; label: string }) {
  const cls =
    tone === "danger" ? "bg-rose-50 text-rose-700"   :
    tone === "warn"   ? "bg-amber-50 text-amber-700" :
                        "bg-sky-50 text-sky-700";
  return (
    <span className={cn("inline-flex items-center gap-1 px-2 py-[3px] rounded-md text-[10px] font-extrabold", cls)}>
      <Icon size={10} />
      {label}
    </span>
  );
}

function InterventionCard({ p }: { p: InterventionPerformance }) {
  const tone = STATUS_TONE[p.status];
  return (
    <div className={cn("rounded-md border px-2.5 py-2", tone.border, tone.bg)}>
      <div className="flex items-start justify-between gap-2">
        <div className={cn("text-[11px] font-extrabold leading-snug", tone.text)}>{p.intervention}</div>
        <StatusPill status={p.status} />
      </div>
      <div className="mt-1 flex items-baseline justify-between gap-2">
        <div className={cn("text-[18px] font-extrabold tabular", tone.text)}>{p.averageScore.toFixed(1)}<span className="text-[10px] opacity-60"> / 10</span></div>
        {p.delta !== undefined && (
          <div className={cn("text-[11px] font-extrabold tabular", p.delta >= 0 ? "text-emerald-700" : "text-rose-700")}>
            {p.delta >= 0 ? "+" : ""}{p.delta.toFixed(1)}
          </div>
        )}
      </div>
      <div className="text-[10px] muted mt-0.5">
        {p.schoolsAssessed} assessed{p.schoolsMissingSsa > 0 ? ` · ${p.schoolsMissingSsa} missing SSA` : ""}
        {p.previousAverage !== undefined && ` · prev ${p.previousAverage.toFixed(1)}`}
      </div>
    </div>
  );
}
