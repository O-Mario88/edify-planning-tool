// Aggregated Field Context — HR + RVP surface.
//
// HR + RVP MUST NOT see named CCEOs or raw daily debrief content.
// Everything is bucketed: barriers by category, support themes by team
// count, team health by team-name only. This protects staff trust.

import { Globe, AlertTriangle, Users, Activity, type LucideIcon } from "lucide-react";
import type { AggregatedFieldContext } from "@/lib/field-intelligence-mock";
import { cn } from "@/lib/utils";

const TEAM_HEALTH_TONE: Record<"On Track" | "Needs Attention" | "Critical", string> = {
  "On Track":        "bg-emerald-100 text-emerald-700",
  "Needs Attention": "bg-amber-100   text-amber-700",
  "Critical":        "bg-rose-100    text-rose-700",
};

export function AggregatedFieldContextCard({
  ctx, title, subtitle,
}: {
  ctx:      AggregatedFieldContext & { country?: string };
  title:    string;
  subtitle: string;
}) {
  return (
    <section className="card p-3.5 space-y-4">
      <header className="flex items-baseline justify-between gap-2 flex-wrap">
        <div className="min-w-0 flex-1">
          <h3 className="text-body-lg font-extrabold tracking-tight inline-flex items-center gap-2">
            <Globe size={14} className="text-[var(--color-edify-primary)]" />
            {title}
          </h3>
          <p className="text-caption muted mt-0.5">{subtitle}</p>
        </div>
        <span className="text-caption muted whitespace-nowrap">
          {ctx.weekLabel}{ctx.country ? ` · ${ctx.country}` : ""}
        </span>
      </header>

      {/* Country-level KPIs */}
      <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-5 gap-2">
        <Stat label="Debriefs"           value={`${ctx.totalDebriefsSubmitted}/${ctx.totalDebriefsExpected}`} />
        <Stat label="Submission rate"    value={`${ctx.debriefSubmissionRatePct}%`} tone={ctx.debriefSubmissionRatePct >= 90 ? "green" : "amber"} />
        <Stat label="Raw achievement"    value={`${ctx.rawAchievementPct}%`} />
        <Stat label="Context-adjusted"   value={`${ctx.contextAdjustedAchievementPct}%`} tone="green" />
        <Stat label="Decisions open"     value={ctx.decisionsForReview.length} tone={ctx.decisionsForReview.length > 0 ? "amber" : "edify"} />
      </div>

      {/* Team health (team names only, no CCEOs) */}
      <Panel Icon={Users} title="Team health">
        <ul className="grid grid-cols-1 md:grid-cols-3 gap-2">
          {ctx.teamHealth.map((t, i) => (
            <li key={i} className="rounded-xl border border-[var(--color-edify-border)] bg-white p-3">
              <div className="flex items-baseline justify-between gap-2">
                <span className="text-body font-extrabold tracking-tight truncate">{t.team}</span>
                <span className={cn("inline-flex items-center px-1.5 py-[2px] rounded-md text-[10px] font-extrabold whitespace-nowrap", TEAM_HEALTH_TONE[t.status])}>
                  {t.status}
                </span>
              </div>
              {t.topBarrier && (
                <div className="text-caption muted mt-1">Top barrier: <span className="font-extrabold text-amber-800">{t.topBarrier}</span></div>
              )}
            </li>
          ))}
        </ul>
      </Panel>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
        <Panel Icon={AlertTriangle} title="Top barriers (country, aggregated)">
          <ul className="space-y-1">
            {ctx.topBarriersByCategory.map((b, i) => (
              <li key={i} className="flex items-baseline justify-between text-[12px]">
                <span>· {b.category}</span>
                <span className="font-extrabold tabular">{b.occurrences}</span>
              </li>
            ))}
          </ul>
        </Panel>
        <Panel Icon={Activity} title="Support themes (teams affected)">
          <ul className="space-y-1">
            {ctx.supportRequestThemes.slice(0, 6).map((t, i) => (
              <li key={i} className="flex items-baseline justify-between text-[12px]">
                <span className="truncate min-w-0 mr-2">· {t.theme}</span>
                <span className="font-extrabold tabular shrink-0">{t.teamsAffected} team{t.teamsAffected === 1 ? "" : "s"}</span>
              </li>
            ))}
          </ul>
        </Panel>
      </div>

      <Panel Icon={AlertTriangle} title="Decisions in review (no staff names exposed)">
        {ctx.decisionsForReview.length === 0 ? (
          <p className="text-[12px] muted">No open decisions in the country pipeline this week.</p>
        ) : (
          <ul className="space-y-1">
            {ctx.decisionsForReview.map((d, i) => (
              <li key={i} className="flex items-baseline justify-between text-[12px] gap-2 flex-wrap">
                <span className="truncate min-w-0 mr-2">· {d.area}</span>
                <span className={cn("inline-flex items-center px-1.5 py-[2px] rounded-md text-[10px] font-extrabold whitespace-nowrap", urgencyTone(d.urgency))}>
                  {d.urgency}
                </span>
              </li>
            ))}
          </ul>
        )}
      </Panel>

      <p className="text-caption muted leading-snug pt-2 border-t border-[var(--color-edify-border)]">
        Staff names and raw daily debrief content are protected. This is aggregated intelligence — what categories are blocking field work and how teams are trending.
      </p>
    </section>
  );
}

function Panel({ Icon, title, children }: { Icon: LucideIcon; title: string; children: React.ReactNode }) {
  return (
    <div className="rounded-xl border border-[var(--color-edify-border)] bg-white p-3">
      <div className="text-[10px] font-bold uppercase tracking-wide muted inline-flex items-center gap-1.5 mb-1.5">
        <Icon size={11} />
        {title}
      </div>
      {children}
    </div>
  );
}

function Stat({ label, value, tone }: { label: string; value: number | string; tone?: "edify" | "green" | "amber" }) {
  const tones = {
    edify: "bg-[var(--color-edify-soft)]/40 border-[var(--color-edify-border)]",
    green: "bg-emerald-50 border-emerald-200",
    amber: "bg-amber-50 border-amber-200",
  } as const;
  return (
    <div className={cn("rounded-xl border px-3 py-2", tones[tone ?? "edify"])}>
      <div className="text-[10px] muted font-bold uppercase tracking-wide truncate">{label}</div>
      <div className="text-[16px] font-extrabold tabular leading-tight">{value}</div>
    </div>
  );
}

function urgencyTone(u: "Low" | "Medium" | "High" | "Critical"): string {
  return ({
    Low:      "bg-slate-100  text-slate-600",
    Medium:   "bg-sky-100    text-sky-700",
    High:     "bg-amber-100  text-amber-800",
    Critical: "bg-rose-100   text-rose-700",
  })[u];
}
