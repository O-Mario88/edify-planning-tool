import Link from "next/link";
import { Trophy, TrendingUp, ArrowRight, BarChart3, Wallet, Database, CloudOff } from "lucide-react";
import { RoleBottomNav } from "@/components/mobile/RoleBottomNav";
import { CorePageHeader } from "@/components/core/CorePageHeader";
import { CoreHealthBanner } from "@/components/core/CoreHealthPanel";
import { CoreExportButton, type ExportRow } from "@/components/core/CoreExportButton";
import { coreBoardData, coreBoardSummary } from "@/lib/core/core-board";
import { coreHealthReport } from "@/lib/core/core-health";
import { getCurrentUser } from "@/lib/auth";
import { backendFetch, isBackendEnabled } from "@/lib/api/backend";
import { cn } from "@/lib/utils";

type CurrentUser = Awaited<ReturnType<typeof getCurrentUser>>;

export const dynamic = "force-dynamic";

// Backend response shapes (edify-api).
type BeHeader = { fy: string; corePlansCount: number; championsCount: number; awaitingSSACount: number; totalCoreSchools: number; planningReadyCount: number };
type BeSchool = { id: string; schoolId: string; name: string; district?: { name: string }; cluster?: { name: string } | null; accountOwnerNameRaw?: string | null; currentFySsaStatus: string; planningReadiness: string; schoolType: string };
type BePage = { data: BeSchool[]; total: number };

const SSA_LABEL: Record<string, string> = { done: "SSA Complete", not_done: "No SSA", scheduled: "SIT Scheduled", partner_assigned: "Partner SSA" };
const READY_LABEL: Record<string, string> = { ready: "Planning Ready", limited: "SSA Required", locked: "Unclustered" };

// Core School Directory. When EDIFY_USE_BACKEND=true, the directory + header
// pills are fetched live from edify-api (the database); otherwise it falls back
// to the in-memory model so the page never breaks.
export default async function CoreSchoolDashboard() {
  const user = await getCurrentUser();
  const health = coreHealthReport();

  // ── Try the backend first ─────────────────────────────────────────
  let be: { header: BeHeader; schools: BeSchool[]; total: number } | null = null;
  let beError: string | null = null;
  if (isBackendEnabled()) {
    const [h, s] = await Promise.all([
      backendFetch<BeHeader>("/filters/core-header-summary", user),
      backendFetch<BePage>("/schools?schoolType=core&pageSize=200", user),
    ]);
    if (h.ok && s.ok) be = { header: h.data, schools: s.data.data, total: s.data.total };
    else beError = (!h.ok && h.error) || (!s.ok && s.error) || "Backend unavailable";
  }

  const body = be
    ? <BackendDirectory be={be} user={user} health={health} />
    : <MockDirectory user={user} health={health} beError={beError} />;
  return body;
}

// ── Backend-driven directory (live from the database) ───────────────
function BackendDirectory({ be, user, health }: { be: { header: BeHeader; schools: BeSchool[]; total: number }; user: CurrentUser; health: ReturnType<typeof coreHealthReport> }) {
  const { header, schools } = be;
  const exportRows: ExportRow[] = schools.map((s) => ({
    schoolId: s.schoolId, school: s.name, district: s.district?.name ?? "", cluster: s.cluster?.name ?? "",
    owner: s.accountOwnerNameRaw ?? "", ssaStatus: s.currentFySsaStatus, planningReadiness: s.planningReadiness,
  }));
  return (
    <>
      <CorePageHeader icon="schools" title="Core Schools" subtitle="Live from the backend database (edify-api). Filtered from the School Directory by core status." searchPlaceholder="Search core schools" />
      <div className="px-3 sm:px-4 lg:px-6 pb-24 lg:pb-6 space-y-3 lg:space-y-4 pt-3">
        <div className="inline-flex items-center gap-1.5 rounded-full bg-emerald-50 text-emerald-700 px-2.5 py-1 text-[11px] font-bold border border-emerald-200">
          <Database size={12} /> Live · backend API · FY{header.fy}
        </div>
        <section className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-2.5">
          <Kpi label="Core schools" value={header.totalCoreSchools} />
          <Kpi label="Core plans" value={header.corePlansCount} />
          <Kpi label="Awaiting SSA" value={header.awaitingSSACount} />
          <Kpi label="Planning ready" value={header.planningReadyCount} />
          <Kpi label="Champions" value={header.championsCount} tone="text-amber-700" />
          <Kpi label="Shown" value={schools.length} />
        </section>

        <CoreHealthBanner report={health} />

        <section className="card p-3.5">
          <div className="flex items-center justify-between gap-2 mb-2 flex-wrap">
            <h2 className="text-[13px] font-extrabold tracking-tight">Core School Directory <span className="muted font-semibold">({be.total})</span></h2>
            <div className="flex items-center gap-3">
              <CoreExportButton rows={exportRows} filename="core-schools" />
              {["ProgramAccountant", "CountryDirector", "CountryProgramLead", "Admin"].includes(user.role) && (
                <Link href="/core-schools/payments" className="inline-flex items-center gap-1 text-[11.5px] font-extrabold text-[var(--color-edify-primary)] hover:text-[var(--color-edify-dark)]"><Wallet size={12} /> Payments</Link>
              )}
              <Link href="/core-schools/analytics" className="inline-flex items-center gap-1 text-[11.5px] font-extrabold text-[var(--color-edify-primary)] hover:text-[var(--color-edify-dark)]"><BarChart3 size={12} /> Analytics</Link>
              <Link href="/planning/core-schools" className="inline-flex items-center gap-1 text-[11.5px] font-extrabold text-[var(--color-edify-primary)] hover:text-[var(--color-edify-dark)]">Planning Console <ArrowRight size={12} /></Link>
            </div>
          </div>
          {schools.length === 0 ? (
            <p className="py-8 text-center text-[12px] muted italic">No core schools in your scope.</p>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-[12px]">
                <thead>
                  <tr className="text-left text-caption muted font-semibold uppercase tracking-wide border-b border-[var(--color-edify-border)]">
                    <th className="py-2 pr-2">School</th><th className="py-2 px-2">District · Cluster</th><th className="py-2 px-2">Owner</th>
                    <th className="py-2 px-2">SSA</th><th className="py-2 px-2">Planning</th><th className="py-2 pl-2" />
                  </tr>
                </thead>
                <tbody className="divide-y divide-[var(--color-edify-divider)]">
                  {schools.map((s) => (
                    <tr key={s.id} className="hover:bg-[var(--color-edify-soft)]/30 align-top">
                      <td className="py-2.5 pr-2">
                        <Link href={`/core-schools/${s.schoolId}`} className="font-extrabold hover:underline">{s.name}</Link>
                        <div className="text-[10px] muted tabular">ID {s.schoolId}</div>
                      </td>
                      <td className="py-2.5 px-2 muted">{s.district?.name ?? "—"}{s.cluster?.name ? ` · ${s.cluster.name}` : ""}</td>
                      <td className="py-2.5 px-2 muted">{s.accountOwnerNameRaw ?? "—"}</td>
                      <td className="py-2.5 px-2"><Pill label={SSA_LABEL[s.currentFySsaStatus] ?? s.currentFySsaStatus} ok={s.currentFySsaStatus === "done"} /></td>
                      <td className="py-2.5 px-2"><Pill label={READY_LABEL[s.planningReadiness] ?? s.planningReadiness} ok={s.planningReadiness === "ready"} warn={s.planningReadiness === "limited"} /></td>
                      <td className="py-2.5 pl-2 text-right"><Link href={`/core-schools/${s.schoolId}`} className="text-[11px] font-bold text-[var(--color-edify-primary)] hover:underline">Detail →</Link></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>
      </div>
      <RoleBottomNav />
    </>
  );
}

function Pill({ label, ok, warn }: { label: string; ok?: boolean; warn?: boolean }) {
  return <span className={cn("inline-flex px-1.5 py-[2px] rounded text-[10px] font-bold", ok ? "bg-emerald-100 text-emerald-700" : warn ? "bg-amber-100 text-amber-700" : "bg-rose-100 text-rose-700")}>{label}</span>;
}

// ── Mock fallback (backend disabled or unreachable) ─────────────────
function MockDirectory({ user, health, beError }: { user: CurrentUser; health: ReturnType<typeof coreHealthReport>; beError: string | null }) {
  const cards = coreBoardData(user.staffId, user.role);
  const summary = coreBoardSummary(cards);
  const exportRows: ExportRow[] = cards.map((c) => ({
    schoolId: c.plan.schoolId, school: c.schoolName, district: c.district, cluster: c.cluster ?? "", owner: c.owner ?? "",
    fy: c.plan.fy, baselineSSA: c.baselineAverage, planStatus: c.plan.status,
    visitsCompleted: c.progress.visitsCompleted, trainingsCompleted: c.progress.trainingsCompleted,
    packagePercent: c.progress.packageCompletionPercent, impactChange: c.impact ? c.impact.averageChange : "", championStatus: c.championStatus,
  }));
  return (
    <>
      <CorePageHeader icon="schools" title="Core Schools" subtitle="Schools onboarded as Core — tracked through 4 visits + 4 trainings, follow-up SSA, impact, and champion pipeline." searchPlaceholder="Search core schools" />
      <div className="px-3 sm:px-4 lg:px-6 pb-24 lg:pb-6 space-y-3 lg:space-y-4 pt-3">
        {beError && (
          <div className="inline-flex items-center gap-1.5 rounded-full bg-amber-50 text-amber-700 px-2.5 py-1 text-[11px] font-bold border border-amber-200">
            <CloudOff size={12} /> Backend offline — showing local data ({beError})
          </div>
        )}
        <section className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-2.5">
          <Kpi label="Core schools" value={summary.plans} />
          <Kpi label="Active plans" value={summary.active} />
          <Kpi label="Awaiting Follow-Up SSA" value={summary.pendingFollowUp} />
          <Kpi label="Impact measured" value={summary.impactMeasured} />
          <Kpi label="Champions" value={summary.champions} tone="text-amber-700" />
          <Kpi label="Visits · Trainings" value={`${summary.visitsDone} · ${summary.trainingsDone}`} />
        </section>
        <CoreHealthBanner report={health} />
        <section className="card p-3.5">
          <div className="flex items-center justify-between gap-2 mb-2 flex-wrap">
            <h2 className="text-[13px] font-extrabold tracking-tight">Core School Directory</h2>
            <div className="flex items-center gap-3">
              <CoreExportButton rows={exportRows} filename="core-schools" />
              <Link href="/core-schools/analytics" className="inline-flex items-center gap-1 text-[11.5px] font-extrabold text-[var(--color-edify-primary)] hover:text-[var(--color-edify-dark)]"><BarChart3 size={12} /> Analytics</Link>
              <Link href="/planning/core-schools" className="inline-flex items-center gap-1 text-[11.5px] font-extrabold text-[var(--color-edify-primary)] hover:text-[var(--color-edify-dark)]">Planning Console <ArrowRight size={12} /></Link>
            </div>
          </div>
          {cards.length === 0 ? (
            <p className="py-8 text-center text-[12px] muted italic">No core schools in your scope yet.</p>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-[12px]">
                <thead><tr className="text-left text-caption muted font-semibold uppercase tracking-wide border-b border-[var(--color-edify-border)]">
                  <th className="py-2 pr-2">School</th><th className="py-2 px-2">District · Cluster</th><th className="py-2 px-2">Owner</th><th className="py-2 px-2 text-right">Baseline</th><th className="py-2 px-2">Package</th><th className="py-2 px-2">Status</th><th className="py-2 px-2">Impact</th><th className="py-2 px-2">Champion</th><th className="py-2 pl-2" />
                </tr></thead>
                <tbody className="divide-y divide-[var(--color-edify-divider)]">
                  {cards.map((c) => (
                    <tr key={c.plan.id} className="hover:bg-[var(--color-edify-soft)]/30 align-top">
                      <td className="py-2.5 pr-2"><Link href={`/core-schools/${c.plan.schoolId}`} className="font-extrabold hover:underline">{c.schoolName}</Link><div className="text-[10px] muted tabular">ID {c.plan.schoolId}</div></td>
                      <td className="py-2.5 px-2 muted">{c.district}{c.cluster ? ` · ${c.cluster}` : ""}</td>
                      <td className="py-2.5 px-2 muted">{c.owner ?? "—"}</td>
                      <td className="py-2.5 px-2 text-right tabular font-bold">{c.baselineAverage.toFixed(1)}</td>
                      <td className="py-2.5 px-2"><div className="flex items-center gap-2"><div className="h-1.5 w-16 rounded-full bg-[var(--color-edify-soft)] overflow-hidden"><div className="h-full rounded-full bg-[var(--color-edify-primary)]" style={{ width: `${c.progress.packageCompletionPercent}%` }} /></div><span className="text-[10.5px] muted tabular">{c.progress.visitsCompleted}V·{c.progress.trainingsCompleted}T</span></div></td>
                      <td className="py-2.5 px-2"><span className="text-[10.5px] font-semibold">{c.plan.status}</span></td>
                      <td className="py-2.5 px-2">{c.impact ? <span className={cn("inline-flex items-center gap-1 font-bold tabular text-[11px]", c.impact.averageChange >= 0 ? "text-emerald-700" : "text-rose-700")}><TrendingUp size={11} /> {c.impact.averageChange >= 0 ? "+" : ""}{c.impact.averageChange}</span> : <span className="text-[11px] muted">—</span>}</td>
                      <td className="py-2.5 px-2">{c.championStatus !== "Not Eligible" ? <span className="inline-flex items-center gap-1 text-[10.5px] font-bold text-amber-700"><Trophy size={11} /> {c.championStatus}</span> : <span className="text-[11px] muted">—</span>}</td>
                      <td className="py-2.5 pl-2 text-right"><Link href={`/core-schools/${c.plan.schoolId}`} className="text-[11px] font-bold text-[var(--color-edify-primary)] hover:underline">Detail →</Link></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>
      </div>
      <RoleBottomNav />
    </>
  );
}

function Kpi({ label, value, tone }: { label: string; value: number | string; tone?: string }) {
  return (
    <div className="card px-3 py-2.5">
      <div className="text-[10px] font-semibold muted leading-tight">{label}</div>
      <div className={cn("text-[18px] font-extrabold tabular leading-none mt-1", tone)}>{value}</div>
    </div>
  );
}
