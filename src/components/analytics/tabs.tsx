"use client";

import {
  AlertTriangle,
  ArrowRight,
  CheckCircle2,
  TrendingDown,
  TrendingUp,
} from "lucide-react";
import {
  activityEffectiveness,
  activityMix,
  activityTrend,
  barrierInsight,
  barrierRows,
  benchmarkBands,
  deliveryFunnel,
  districtImprovement,
  evidenceQuality,
  fundingFlow,
  fundingSummary,
  funnelReturned,
  heatColumns,
  literacyByClass,
  literacyTrend,
  oneTestKpis,
  partnerRows,
  schoolImprovementSummary,
  schoolRows,
  ssaDataGaps,
  ssaInterventions,
  ssaLiteracyCorrelation,
  ssaLiteracyScatter,
  ssaMovement,
  ssaRiskBuckets,
  ssaTrend,
  staffHeatmap,
  staffRows,
  type HeatLevel,
  type PartnerRow,
  type SchoolRow,
  type StaffRow,
} from "@/lib/analytics-mock";
import {
  ACard,
  Avatar,
  Bar,
  ColumnChart,
  DataTable,
  Donut,
  GroupedBarRow,
  Legend,
  LineChart,
  StatusBadge,
  TONE,
  type Tone,
} from "./primitives";
import { cn } from "@/lib/utils";

// ════════════════════════════════════════════════════════════════════
//  Shared helpers
// ════════════════════════════════════════════════════════════════════

const STAFF_STATUS_TONE: Record<StaffRow["status"], Tone> = {
  "On Track": "emerald",
  "Needs Attention": "amber",
  "Support Needed": "amber",
  "Critical": "rose",
};

const SCHOOL_STATUS_TONE: Record<SchoolRow["status"], Tone> = {
  Improving: "emerald",
  Stable: "sky",
  Declining: "amber",
  Critical: "rose",
  "Champion Candidate": "violet",
  "No Current Data": "slate",
};

const PARTNER_STATUS_TONE: Record<PartnerRow["status"], Tone> = {
  "Strong Partner": "emerald",
  Reliable: "sky",
  "Needs Coaching": "amber",
  "High Return Rate": "amber",
  "At Risk": "rose",
};

function delta(n: number, unit = "") {
  const up = n > 0;
  const flat = n === 0;
  return (
    <span
      className={cn(
        "inline-flex items-center gap-0.5 text-[11px] font-extrabold tabular",
        flat ? "text-slate-400" : up ? "text-emerald-600" : "text-rose-600",
      )}
    >
      {!flat && (up ? <TrendingUp size={11} strokeWidth={2.6} /> : <TrendingDown size={11} strokeWidth={2.6} />)}
      {up ? "+" : ""}
      {n}
      {unit}
    </span>
  );
}

// ════════════════════════════════════════════════════════════════════
//  1 · OVERVIEW
// ════════════════════════════════════════════════════════════════════

export function OverviewTab() {
  const watchlist = [...staffRows]
    .filter((s) => s.status !== "On Track")
    .sort((a, b) => a.verified / a.planned - b.verified / b.planned);

  return (
    <>
      <section className="grid grid-cols-12 gap-4 items-start">
        {/* Funnel */}
        <div className="col-span-12 xl:col-span-7">
          <ACard
            title="Plan → Done → Verified"
            subtitle="Where field work is getting stuck — only IA-verified work counts as official"
          >
            <DeliveryFunnel />
          </ACard>
        </div>

        {/* School improvement summary */}
        <div className="col-span-12 xl:col-span-5">
          <ACard title="School Improvement" subtitle="Movement across all assessed schools this FY">
            <SchoolImprovementSummary />
          </ACard>
        </div>
      </section>

      <section className="grid grid-cols-12 gap-4 items-start">
        {/* SSA + One Test dual trend */}
        <div className="col-span-12 xl:col-span-7">
          <ACard
            title="SSA & Literacy Trend"
            subtitle="Average SSA score and One Test literacy moving together"
            action={
              <Legend
                items={[
                  { label: "SSA score", tone: "emerald" },
                  { label: "Literacy %", tone: "violet" },
                ]}
              />
            }
          >
            <LineChart
              labels={ssaTrend.map((p) => p.label)}
              yMax={100}
              series={[
                { label: "SSA (×10)", tone: "emerald", values: ssaTrend.map((p) => p.score * 10) },
                { label: "Literacy", tone: "violet", values: [44, 45, 47, 48, 49, 50] },
              ]}
            />
            <p className="text-caption text-slate-400 font-semibold mt-2">
              SSA shown ×10 for shared axis. Verified-coached schools drive both curves.
            </p>
          </ACard>
        </div>

        {/* Staff watchlist */}
        <div className="col-span-12 xl:col-span-5">
          <ACard
            title="Staff Support Watchlist"
            subtitle="Lowest verified-completion ratio — needs supervisor support"
            action={
              <a href="#support" className="text-[11px] font-extrabold text-sky-700 hover:text-sky-800">
                View All →
              </a>
            }
          >
            <ul className="flex flex-col gap-2">
              {watchlist.map((s, i) => {
                const ratio = Math.round((s.verified / s.planned) * 100);
                return (
                  <li
                    key={s.id}
                    className={cn(
                      "rounded-xl ring-1 ring-[var(--color-edify-border)] bg-white p-2.5 flex items-center gap-2.5 tile-in",
                      `stagger-${i + 1}`,
                    )}
                  >
                    <Avatar initials={s.initials} i={i} size={34} />
                    <div className="min-w-0 flex-1">
                      <div className="text-[12px] font-extrabold text-slate-900 truncate">
                        {s.name}
                      </div>
                      <div className="text-[10px] text-slate-500 font-semibold truncate">
                        {s.district} · PL {s.programLead}
                      </div>
                    </div>
                    <div className="w-[78px] shrink-0">
                      <div className="flex items-center justify-between mb-1">
                        <span className="text-[9px] text-slate-400 font-bold uppercase">Verified</span>
                        <span className="text-caption font-extrabold tabular text-slate-800">{ratio}%</span>
                      </div>
                      <Bar pct={ratio} tone={ratio >= 60 ? "amber" : "rose"} />
                    </div>
                    <StatusBadge label={s.status} tone={STAFF_STATUS_TONE[s.status]} />
                  </li>
                );
              })}
            </ul>
          </ACard>
        </div>
      </section>
    </>
  );
}

function DeliveryFunnel() {
  const top = deliveryFunnel[0].value;
  return (
    <div className="flex flex-col gap-2.5">
      {deliveryFunnel.map((s, i) => {
        const pct = Math.round((s.value / top) * 100);
        const drop = i > 0 ? deliveryFunnel[i - 1].value - s.value : 0;
        return (
          <div key={s.label} className={cn("tile-in", `stagger-${i + 1}`)}>
            <div className="flex items-center justify-between gap-2 mb-1">
              <span className="text-[11.5px] font-extrabold text-slate-800">
                {s.label}
                <span className="text-[10px] text-slate-400 font-semibold ml-1.5">{s.note}</span>
              </span>
              <div className="flex items-center gap-2 shrink-0">
                {drop > 0 && (
                  <span className="text-[10px] font-extrabold text-rose-500 tabular">−{drop}</span>
                )}
                <span className="text-[13px] font-extrabold tabular num-hero text-slate-900 w-[52px] text-right">
                  {s.value.toLocaleString()}
                </span>
              </div>
            </div>
            <div className="h-[14px] rounded-md bg-slate-100 overflow-hidden">
              <div
                className={cn("h-full rounded-md bg-gradient-to-r flex items-center justify-end pr-2", TONE[s.tone].barFrom)}
                style={{ width: `${pct}%` }}
              >
                <span className="text-[9px] font-extrabold text-white/90 tabular">{pct}%</span>
              </div>
            </div>
          </div>
        );
      })}
      <div className="mt-1.5 rounded-xl bg-rose-50 ring-1 ring-rose-100 px-3 py-2 flex items-center gap-2">
        <AlertTriangle size={14} className="text-rose-500 shrink-0" strokeWidth={2.4} />
        <span className="text-[11px] font-semibold text-rose-700">
          <span className="font-extrabold tabular">{funnelReturned.value}</span> {funnelReturned.label} — evidence
          sent back to staff. Not yet counted as verified.
        </span>
      </div>
    </div>
  );
}

function SchoolImprovementSummary() {
  const s = schoolImprovementSummary;
  const total = s.improved + s.noChange + s.declined + s.noData;
  const donut = [
    { label: "Improved", value: s.improved, color: TONE.emerald.hex },
    { label: "No change", value: s.noChange, color: TONE.sky.hex },
    { label: "Declined", value: s.declined, color: TONE.rose.hex },
    { label: "No data", value: s.noData, color: TONE.slate.hex },
  ];
  return (
    <div className="flex items-center gap-4 flex-wrap">
      <Donut
        data={donut}
        size={150}
        centerTop="Schools"
        centerMain={total.toLocaleString()}
        centerSub="assessed this FY"
      />
      <ul className="flex-1 min-w-[160px] flex flex-col gap-2.5">
        {donut.map((d) => (
          <li key={d.label} className="flex items-center gap-2">
            <span className="w-2.5 h-2.5 rounded-[3px] shrink-0" style={{ backgroundColor: d.color }} />
            <span className="flex-1 text-[11.5px] font-semibold text-slate-600">{d.label}</span>
            <span className="text-[13px] font-extrabold tabular num-hero text-slate-900">{d.value}</span>
            <span className="w-[34px] text-right text-[10px] font-extrabold tabular text-slate-400">
              {Math.round((d.value / total) * 100)}%
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}

// ════════════════════════════════════════════════════════════════════
//  2 · STAFF PERFORMANCE
// ════════════════════════════════════════════════════════════════════

export function StaffTab() {
  const maxAct = Math.max(...staffRows.map((s) => s.planned));
  const mixTotal = activityMix.reduce((a, m) => a + m.count, 0);

  return (
    <>
      <section className="grid grid-cols-12 gap-4 items-start">
        {/* Completion bars */}
        <div className="col-span-12 xl:col-span-7">
          <ACard
            title="Staff Activity Completion"
            subtitle="Planned vs completed vs verified — completed-but-unverified shown separately"
            action={
              <Legend
                items={[
                  { label: "Planned", tone: "slate" },
                  { label: "Completed", tone: "sky" },
                  { label: "Verified", tone: "emerald" },
                ]}
              />
            }
          >
            <div className="flex flex-col gap-3">
              {staffRows.map((s) => (
                <GroupedBarRow
                  key={s.id}
                  name={s.name}
                  max={maxAct}
                  meta={`${Math.round((s.verified / s.planned) * 100)}% verified`}
                  series={[
                    { label: "Planned", value: s.planned, tone: "slate" },
                    { label: "Completed", value: s.completed, tone: "sky" },
                    { label: "Verified", value: s.verified, tone: "emerald" },
                  ]}
                />
              ))}
            </div>
          </ACard>
        </div>

        <div className="col-span-12 xl:col-span-5 flex flex-col gap-4">
          {/* Monthly trend */}
          <ACard
            title="Monthly Activity Trend"
            action={
              <Legend
                items={[
                  { label: "Planned", tone: "slate" },
                  { label: "Completed", tone: "sky" },
                  { label: "Verified", tone: "emerald" },
                ]}
              />
            }
          >
            <LineChart
              labels={activityTrend.map((p) => p.label)}
              height={150}
              series={[
                { label: "Planned", tone: "slate", values: activityTrend.map((p) => p.planned), dashed: true },
                { label: "Completed", tone: "sky", values: activityTrend.map((p) => p.completed) },
                { label: "Verified", tone: "emerald", values: activityTrend.map((p) => p.verified) },
              ]}
            />
          </ACard>

          {/* Activity mix */}
          <ACard title="Activity Mix" subtitle="What CCEOs are spending field time on">
            <div className="flex items-center gap-4 flex-wrap">
              <Donut
                data={activityMix.map((m) => ({ label: m.label, value: m.count, color: m.color }))}
                size={140}
                centerTop="Activities"
                centerMain={mixTotal.toLocaleString()}
              />
              <ul className="flex-1 min-w-[150px] flex flex-col gap-1.5">
                {activityMix.map((m) => (
                  <li key={m.label} className="flex items-center gap-2">
                    <span className="w-2 h-2 rounded-full shrink-0" style={{ backgroundColor: m.color }} />
                    <span className="flex-1 text-caption font-semibold text-slate-600 truncate">{m.label}</span>
                    <span className="text-caption font-extrabold tabular text-slate-800">{m.count}</span>
                  </li>
                ))}
              </ul>
            </div>
          </ACard>
        </div>
      </section>

      {/* Heatmap */}
      <ACard title="Staff Readiness Heatmap" subtitle="Green on track · amber needs attention · red critical">
        <Heatmap />
      </ACard>

      {/* Staff table */}
      <ACard title="CCEO Activity Table" subtitle="Verified delivery, evidence and accountability per staff member">
        <DataTable<StaffRow>
          rowKey={(r) => r.id}
          minWidth={900}
          rows={staffRows}
          columns={[
            { key: "cceo", header: "CCEO", render: (r) => (
              <div className="flex items-center gap-2 min-w-0">
                <Avatar initials={r.initials} size={26} />
                <div className="min-w-0">
                  <div className="text-[11.5px] font-extrabold text-slate-900 truncate">{r.name}</div>
                  <div className="text-[9.5px] text-slate-400 font-semibold truncate">PL {r.programLead}</div>
                </div>
              </div>
            )},
            { key: "planned", header: "Planned", align: "right", render: (r) => <span className="text-[11.5px] font-semibold tabular text-slate-600">{r.planned}</span> },
            { key: "completed", header: "Completed", align: "right", render: (r) => <span className="text-[11.5px] font-semibold tabular text-slate-600">{r.completed}</span> },
            { key: "verified", header: "Verified", align: "right", render: (r) => <span className="text-[12px] font-extrabold tabular num-hero text-slate-900">{r.verified}</span> },
            { key: "sf", header: "SF Pending", align: "right", render: (r) => <span className={cn("text-[11.5px] font-extrabold tabular", r.salesforcePending > 10 ? "text-rose-600" : "text-slate-600")}>{r.salesforcePending}</span> },
            { key: "debrief", header: "Debrief", align: "right", render: (r) => <span className="text-[11.5px] font-semibold tabular text-slate-600">{r.debriefRate}%</span> },
            { key: "ssa", header: "SSA Gain", align: "right", render: (r) => delta(r.ssaGain) },
            { key: "ot", header: "Literacy", align: "right", render: (r) => delta(r.oneTestGain, "pp") },
            { key: "status", header: "Support Status", render: (r) => <StatusBadge label={r.status} tone={STAFF_STATUS_TONE[r.status]} /> },
          ]}
        />
      </ACard>
    </>
  );
}

const HEAT_COLOR: Record<HeatLevel, string> = {
  green: "bg-emerald-400",
  amber: "bg-amber-400",
  red: "bg-rose-400",
  gray: "bg-slate-200",
};

function Heatmap() {
  return (
    <div className="overflow-x-auto -mx-1 px-1">
      <div className="min-w-[680px]">
        <div className="flex items-center gap-1 mb-1.5 pl-[136px]">
          {heatColumns.map((c) => (
            <span key={c} className="flex-1 text-center text-[8.5px] text-slate-400 font-extrabold uppercase tracking-[0.04em]">
              {c}
            </span>
          ))}
        </div>
        <div className="flex flex-col gap-1">
          {staffHeatmap.map((row) => (
            <div key={row.staff} className="flex items-center gap-1">
              <span className="w-[132px] shrink-0 text-[11px] font-extrabold text-slate-700 truncate pr-2">
                {row.staff}
              </span>
              {row.cells.map((cell, ci) => (
                <span
                  key={ci}
                  className={cn("flex-1 h-7 rounded-md", HEAT_COLOR[cell])}
                  title={`${heatColumns[ci]}: ${cell}`}
                />
              ))}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

// ════════════════════════════════════════════════════════════════════
//  3 · SCHOOL IMPROVEMENT
// ════════════════════════════════════════════════════════════════════

export function SchoolsTab() {
  const maxImproved = Math.max(...districtImprovement.map((d) => d.improved + d.declined));
  return (
    <>
      <section className="grid grid-cols-12 gap-4 items-start">
        <div className="col-span-12 xl:col-span-6">
          <ACard title="Improvement by District" subtitle="Schools improved vs declined, with average SSA + literacy gain">
            <div className="flex flex-col gap-3">
              {districtImprovement.map((d) => (
                <div key={d.district}>
                  <div className="flex items-center justify-between mb-1">
                    <span className="text-[11.5px] font-extrabold text-slate-800">{d.district}</span>
                    <div className="flex items-center gap-2.5">
                      <span className="text-[10px] font-extrabold text-emerald-600 tabular">SSA +{d.ssaGain}</span>
                      <span className="text-[10px] font-extrabold text-violet-600 tabular">Lit +{d.oneTestGain}pp</span>
                    </div>
                  </div>
                  <div className="h-[10px] rounded-md bg-slate-100 overflow-hidden flex">
                    <div
                      className="h-full bg-gradient-to-r from-emerald-400 to-emerald-600"
                      style={{ width: `${(d.improved / maxImproved) * 100}%` }}
                      title={`${d.improved} improved`}
                    />
                    <div
                      className="h-full bg-gradient-to-r from-rose-400 to-rose-500"
                      style={{ width: `${(d.declined / maxImproved) * 100}%` }}
                      title={`${d.declined} declined`}
                    />
                  </div>
                  <div className="flex items-center gap-3 mt-0.5">
                    <span className="text-[9.5px] font-semibold text-emerald-600">{d.improved} improved</span>
                    <span className="text-[9.5px] font-semibold text-rose-500">{d.declined} declined</span>
                  </div>
                </div>
              ))}
            </div>
          </ACard>
        </div>

        <div className="col-span-12 xl:col-span-6">
          <ACard
            title="Activity-to-Outcome Effectiveness"
            subtitle="Which verified activities are most associated with school improvement"
          >
            <DataTable<(typeof activityEffectiveness)[number]>
              rowKey={(r) => r.activity}
              minWidth={420}
              rows={activityEffectiveness}
              columns={[
                { key: "act", header: "Activity", render: (r) => <span className="text-[11px] font-extrabold text-slate-800">{r.activity}</span> },
                { key: "v", header: "Verified", align: "right", render: (r) => <span className="text-[11px] font-semibold tabular text-slate-600">{r.verified}</span> },
                { key: "ssa", header: "SSA", align: "right", render: (r) => delta(r.ssaGain) },
                { key: "ot", header: "Literacy", align: "right", render: (r) => delta(r.oneTestGain, "pp") },
                { key: "imp", header: "Improved", align: "right", render: (r) => (
                  <span className="text-[11px] font-extrabold tabular text-slate-800">{r.schoolsImprovedPct}%</span>
                )},
              ]}
            />
            <p className="text-caption text-slate-400 font-semibold mt-2">
              In-School coaching shows the strongest link to verified school improvement.
            </p>
          </ACard>
        </div>
      </section>

      <ACard
        title="School Improvement Table"
        subtitle="Baseline vs current SSA and literacy, with recommended next action"
      >
        <DataTable<SchoolRow>
          rowKey={(r) => r.id}
          minWidth={1000}
          rows={schoolRows}
          columns={[
            { key: "school", header: "School", render: (r) => (
              <div className="min-w-0">
                <div className="text-[11.5px] font-extrabold text-slate-900 truncate">{r.name}</div>
                <div className="text-[9.5px] text-slate-400 font-semibold truncate">{r.district} · {r.cluster}</div>
              </div>
            )},
            { key: "cceo", header: "CCEO", render: (r) => <span className="text-[11px] font-semibold text-slate-600">{r.cceo}</span> },
            { key: "ssa", header: "SSA (base→now)", align: "right", render: (r) => (
              r.currentSsa === 0
                ? <span className="text-caption text-slate-400 font-semibold">—</span>
                : <span className="text-[11px] font-semibold tabular text-slate-600">{r.baselineSsa} → <span className="font-extrabold text-slate-900">{r.currentSsa}</span></span>
            )},
            { key: "ssad", header: "SSA Δ", align: "right", render: (r) => r.currentSsa === 0 ? <span className="text-slate-300">—</span> : delta(Number((r.currentSsa - r.baselineSsa).toFixed(1))) },
            { key: "lit", header: "Literacy Δ", align: "right", render: (r) => r.currentOneTest === 0 ? <span className="text-slate-300">—</span> : delta(r.currentOneTest - r.baselineOneTest, "pp") },
            { key: "v", header: "Verified", align: "right", render: (r) => <span className="text-[11px] font-semibold tabular text-slate-600">{r.activitiesVerified}</span> },
            { key: "status", header: "Status", render: (r) => <StatusBadge label={r.status} tone={SCHOOL_STATUS_TONE[r.status]} /> },
            { key: "next", header: "Recommended Next Action", render: (r) => (
              <span className="text-caption font-semibold text-slate-500 inline-flex items-center gap-1">
                <ArrowRight size={10} className="text-sky-500 shrink-0" />
                {r.nextAction}
              </span>
            )},
          ]}
        />
      </ACard>
    </>
  );
}

// ════════════════════════════════════════════════════════════════════
//  4 · SSA
// ════════════════════════════════════════════════════════════════════

export function SsaTab() {
  const maxI = 10;
  return (
    <>
      <section className="grid grid-cols-12 gap-4 items-start">
        <div className="col-span-12 xl:col-span-7">
          <ACard title="SSA Score Trend" subtitle="Country average School Self-Assessment, quarterly">
            <LineChart
              labels={ssaTrend.map((p) => p.label)}
              yMax={10}
              series={[{ label: "SSA", tone: "emerald", values: ssaTrend.map((p) => p.score) }]}
            />
          </ACard>
        </div>
        <div className="col-span-12 xl:col-span-5">
          <ACard title="SSA Risk Bands" subtitle="School distribution across the SSA risk thresholds">
            <ul className="flex flex-col gap-2.5">
              {ssaRiskBuckets.map((b) => {
                const total = ssaRiskBuckets.reduce((a, x) => a + x.count, 0);
                const pct = Math.round((b.count / total) * 100);
                return (
                  <li key={b.label}>
                    <div className="flex items-center justify-between mb-1">
                      <span className="text-[11px] font-semibold text-slate-600">{b.label}</span>
                      <span className="text-[12px] font-extrabold tabular text-slate-900">{b.count}</span>
                    </div>
                    <Bar pct={pct} tone={b.tone} />
                  </li>
                );
              })}
            </ul>
            <div className="mt-3 pt-3 border-t border-[var(--color-edify-divider)] grid grid-cols-3 gap-2">
              <DataGap label="No current FY" value={ssaDataGaps.noCurrentFy} />
              <DataGap label="Needs verify" value={ssaDataGaps.needsVerification} />
              <DataGap label="Old SSA only" value={ssaDataGaps.oldSsaOnly} />
            </div>
          </ACard>
        </div>
      </section>

      <section className="grid grid-cols-12 gap-4 items-start">
        <div className="col-span-12 xl:col-span-7">
          <ACard title="SSA by Intervention" subtitle="Baseline vs current across the 8 interventions">
            <div className="flex flex-col gap-2.5">
              {ssaInterventions.map((iv) => (
                <div key={iv.label}>
                  <div className="flex items-center justify-between mb-1">
                    <span className="text-[11px] font-semibold text-slate-600">{iv.label}</span>
                    <div className="flex items-center gap-2">
                      <span className="text-[10px] text-slate-400 font-semibold tabular">{iv.baseline}</span>
                      <ArrowRight size={9} className="text-slate-300" />
                      <span className="text-[11.5px] font-extrabold tabular text-slate-900">{iv.current}</span>
                      {delta(Number((iv.current - iv.baseline).toFixed(1)))}
                    </div>
                  </div>
                  <div className="relative h-[6px] rounded-full bg-slate-100 overflow-hidden">
                    <div className="absolute h-full rounded-full bg-slate-300" style={{ width: `${(iv.baseline / maxI) * 100}%` }} />
                    <div className="absolute h-full rounded-full bg-gradient-to-r from-emerald-400 to-emerald-600" style={{ width: `${(iv.current / maxI) * 100}%` }} />
                  </div>
                </div>
              ))}
            </div>
          </ACard>
        </div>
        <div className="col-span-12 xl:col-span-5">
          <ACard title="SSA Movement" subtitle="Schools changing risk band this FY — improvement, not just averages">
            <div className="grid grid-cols-2 gap-3">
              <MovementCard label="Red → Amber" value={ssaMovement.redToAmber} tone="amber" up />
              <MovementCard label="Amber → Green" value={ssaMovement.amberToGreen} tone="emerald" up />
              <MovementCard label="Held in Green" value={ssaMovement.greenHeld} tone="sky" up />
              <MovementCard label="Dropped back" value={ssaMovement.droppedBack} tone="rose" up={false} />
            </div>
            <p className="text-caption text-slate-400 font-semibold mt-3">
              104 schools moved up a risk band; 27 slipped — net positive movement of +77.
            </p>
          </ACard>
        </div>
      </section>
    </>
  );
}

function DataGap({ label, value }: { label: string; value: number }) {
  return (
    <div className="rounded-lg bg-amber-50 ring-1 ring-amber-100 px-2 py-1.5 text-center">
      <div className="text-[15px] font-extrabold tabular num-hero text-amber-700 leading-none">{value}</div>
      <div className="text-[8.5px] font-extrabold uppercase tracking-[0.04em] text-amber-600/80 mt-1">{label}</div>
    </div>
  );
}

function MovementCard({ label, value, tone, up }: { label: string; value: number; tone: Tone; up: boolean }) {
  return (
    <div className={cn("rounded-xl ring-1 px-3 py-2.5", TONE[tone].soft, TONE[tone].ring)}>
      <div className="flex items-center gap-1.5">
        {up ? <TrendingUp size={12} className={TONE[tone].text} strokeWidth={2.6} /> : <TrendingDown size={12} className={TONE[tone].text} strokeWidth={2.6} />}
        <span className="text-[15px] font-extrabold tabular num-hero text-slate-900 leading-none">{value}</span>
      </div>
      <div className="text-[9.5px] font-extrabold uppercase tracking-[0.04em] text-slate-500 mt-1">{label}</div>
    </div>
  );
}

// ════════════════════════════════════════════════════════════════════
//  5 · ONE TEST LITERACY
// ════════════════════════════════════════════════════════════════════

export function OneTestTab() {
  const benchTotal = benchmarkBands.reduce((a, b) => a + b.count, 0);
  const maxClass = 70;
  return (
    <>
      {/* KPI cards */}
      <section className="grid grid-cols-2 md:grid-cols-3 xl:grid-cols-6 gap-3">
        {oneTestKpis.map((k, i) => (
          <article key={k.label} className={cn("card p-3.5 tile-in", `stagger-${i + 1}`)}>
            <div className="text-[9px] font-extrabold uppercase tracking-[0.07em] text-slate-500 leading-tight">
              {k.label}
            </div>
            <div className={cn("text-[20px] font-extrabold tabular num-hero leading-none mt-1.5", TONE[k.tone].text)}>
              {k.value}
            </div>
          </article>
        ))}
      </section>

      <section className="grid grid-cols-12 gap-4 items-start">
        <div className="col-span-12 xl:col-span-5">
          <ACard title="Literacy Trend" subtitle="Average One Test score · baseline → midline → endline">
            <LineChart
              labels={literacyTrend.map((p) => p.label)}
              yMax={100}
              yUnit="%"
              height={150}
              series={[{ label: "Literacy", tone: "violet", values: literacyTrend.map((p) => p.score) }]}
            />
          </ACard>
        </div>
        <div className="col-span-12 xl:col-span-7">
          <ACard title="Benchmark Distribution" subtitle={`${benchTotal.toLocaleString()} learners assessed across 4 proficiency bands`}>
            <div className="h-7 rounded-lg overflow-hidden flex mb-2.5">
              {benchmarkBands.map((b) => (
                <div
                  key={b.label}
                  className="h-full flex items-center justify-center"
                  style={{ width: `${(b.count / benchTotal) * 100}%`, backgroundColor: b.color }}
                  title={`${b.label}: ${b.count}`}
                >
                  <span className="text-[9px] font-extrabold text-white/95 tabular">
                    {Math.round((b.count / benchTotal) * 100)}%
                  </span>
                </div>
              ))}
            </div>
            <ul className="grid grid-cols-2 sm:grid-cols-4 gap-2">
              {benchmarkBands.map((b) => (
                <li key={b.label} className="flex items-center gap-1.5">
                  <span className="w-2.5 h-2.5 rounded-[3px] shrink-0" style={{ backgroundColor: b.color }} />
                  <div className="min-w-0">
                    <div className="text-[10px] font-semibold text-slate-500 truncate">{b.label}</div>
                    <div className="text-[11.5px] font-extrabold tabular text-slate-900">{b.count.toLocaleString()}</div>
                  </div>
                </li>
              ))}
            </ul>
          </ACard>
        </div>
      </section>

      <section className="grid grid-cols-12 gap-4 items-start">
        <div className="col-span-12 xl:col-span-7">
          <ACard
            title="Literacy by Class"
            subtitle="Baseline vs current One Test score, P1–P7"
            action={
              <Legend items={[{ label: "Baseline", tone: "slate" }, { label: "Current", tone: "emerald" }]} />
            }
          >
            <ColumnChart
              max={maxClass}
              rows={literacyByClass.map((c) => ({ label: c.grade, a: c.baseline, b: c.current }))}
            />
          </ACard>
        </div>
        <div className="col-span-12 xl:col-span-5">
          <ACard
            title="SSA → Literacy Relationship"
            subtitle="Schools with rising SSA show the strongest literacy gains"
          >
            <ul className="flex flex-col gap-2">
              {ssaLiteracyCorrelation.map((c) => (
                <li key={c.band} className={cn("rounded-xl ring-1 px-3 py-2.5", TONE[c.tone].soft, TONE[c.tone].ring)}>
                  <div className="flex items-center justify-between gap-2">
                    <span className="text-[11px] font-semibold text-slate-700">{c.band}</span>
                    <span className="text-[15px] font-extrabold tabular num-hero text-slate-900">
                      {c.literacyGain > 0 ? "+" : ""}{c.literacyGain}pp
                    </span>
                  </div>
                  <div className="text-[9.5px] font-semibold text-slate-400 mt-0.5">
                    {c.schools} schools in this band
                  </div>
                </li>
              ))}
            </ul>
            <div className="mt-3">
              <Scatter />
            </div>
          </ACard>
        </div>
      </section>
    </>
  );
}

function Scatter() {
  const W = 320;
  const H = 110;
  const padL = 26;
  const padB = 18;
  const xs = ssaLiteracyScatter.map((p) => p.x);
  const ys = ssaLiteracyScatter.map((p) => p.y);
  const xMin = Math.min(...xs) - 0.2;
  const xMax = Math.max(...xs) + 0.2;
  const yMin = Math.min(...ys) - 2;
  const yMax = Math.max(...ys) + 2;
  const px = (x: number) => padL + ((x - xMin) / (xMax - xMin)) * (W - padL - 6);
  const py = (y: number) => 6 + (1 - (y - yMin) / (yMax - yMin)) * (H - 6 - padB);
  const zeroX = px(0);
  const zeroY = py(0);
  return (
    <div>
      <div className="text-[9.5px] font-extrabold uppercase tracking-[0.06em] text-slate-400 mb-1">
        SSA change vs literacy change · each dot a school
      </div>
      <svg width="100%" viewBox={`0 0 ${W} ${H}`} className="block" style={{ height: H }}>
        <line x1={zeroX} y1={6} x2={zeroX} y2={H - padB} stroke="#E2E8F0" strokeWidth={1} strokeDasharray="3 3" />
        <line x1={padL} y1={zeroY} x2={W - 6} y2={zeroY} stroke="#E2E8F0" strokeWidth={1} strokeDasharray="3 3" />
        {ssaLiteracyScatter.map((p, i) => (
          <circle
            key={i}
            cx={px(p.x)}
            cy={py(p.y)}
            r={4}
            fill={p.y >= 0 && p.x >= 0 ? TONE.emerald.hex : TONE.rose.hex}
            fillOpacity={0.8}
          />
        ))}
        <text x={padL} y={H - 4} fontSize={8} fontWeight={700} fill="#94A3B8">− SSA</text>
        <text x={W - 6} y={H - 4} textAnchor="end" fontSize={8} fontWeight={700} fill="#94A3B8">+ SSA</text>
      </svg>
    </div>
  );
}

// ════════════════════════════════════════════════════════════════════
//  6 · PARTNER DELIVERY
// ════════════════════════════════════════════════════════════════════

export function PartnersTab() {
  return (
    <>
      <section className="grid grid-cols-12 gap-4 items-start">
        <div className="col-span-12 xl:col-span-8">
          <ACard title="Partner Performance" subtitle="Partner work only counts once evidence is IA-verified">
            <DataTable<PartnerRow>
              rowKey={(r) => r.name}
              minWidth={760}
              rows={partnerRows}
              columns={[
                { key: "p", header: "Partner", render: (r) => <span className="text-[11.5px] font-extrabold text-slate-900">{r.name}</span> },
                { key: "s", header: "Schools", align: "right", render: (r) => <span className="text-[11px] font-semibold tabular text-slate-600">{r.assignedSchools}</span> },
                { key: "c", header: "Completed", align: "right", render: (r) => <span className="text-[11px] font-semibold tabular text-slate-600">{r.completed}</span> },
                { key: "v", header: "Verified", align: "right", render: (r) => <span className="text-[12px] font-extrabold tabular num-hero text-slate-900">{r.verified}</span> },
                { key: "r", header: "Returned", align: "right", render: (r) => <span className={cn("text-[11px] font-extrabold tabular", r.returned >= 5 ? "text-rose-600" : "text-slate-500")}>{r.returned}</span> },
                { key: "eq", header: "Evidence", align: "right", render: (r) => <span className="text-[11px] font-semibold tabular text-slate-600">{r.evidenceQuality}%</span> },
                { key: "ssa", header: "SSA", align: "right", render: (r) => delta(r.ssaGain) },
                { key: "ot", header: "Literacy", align: "right", render: (r) => delta(r.oneTestGain, "pp") },
                { key: "st", header: "Status", render: (r) => <StatusBadge label={r.status} tone={PARTNER_STATUS_TONE[r.status]} /> },
              ]}
            />
          </ACard>
        </div>
        <div className="col-span-12 xl:col-span-4">
          <ACard title="Evidence Quality" subtitle="Composite evidence score across all field work">
            <div className="flex items-center gap-3 mb-3">
              <Donut
                data={[
                  { label: "Score", value: evidenceQuality.score, color: TONE.emerald.hex },
                  { label: "Gap", value: 100 - evidenceQuality.score, color: "#EEF2F4" },
                ]}
                size={96}
                thickness={14}
                centerMain={`${evidenceQuality.score}`}
                centerSub="quality"
              />
              <p className="text-caption font-semibold text-slate-500 flex-1">
                Built from Salesforce ID, evidence upload, GPS capture, IA verification and partner forms.
              </p>
            </div>
            <ul className="flex flex-col gap-2">
              {evidenceQuality.breakdown.map((b) => (
                <li key={b.label}>
                  <div className="flex items-center justify-between mb-1">
                    <span className="text-caption font-semibold text-slate-600">{b.label}</span>
                    <span className="text-[11px] font-extrabold tabular text-slate-900">{b.pct}%</span>
                  </div>
                  <Bar pct={b.pct} tone={b.tone} />
                </li>
              ))}
            </ul>
          </ACard>
        </div>
      </section>
    </>
  );
}

// ════════════════════════════════════════════════════════════════════
//  7 · FUNDING
// ════════════════════════════════════════════════════════════════════

export function FundingTab() {
  const f = fundingSummary;
  return (
    <>
      <section className="grid grid-cols-12 gap-4 items-start">
        <div className="col-span-12 xl:col-span-7">
          <ACard title="Funding → Verified Delivery" subtitle="Does disbursed money turn into verified field work?">
            <div className="flex flex-col gap-2.5">
              {fundingFlow.map((s, i) => (
                <div key={s.label} className={cn("tile-in", `stagger-${i + 1}`)}>
                  <div className="flex items-center justify-between mb-1">
                    <span className="text-[11.5px] font-extrabold text-slate-800">{s.label}</span>
                    <span className="text-body font-extrabold tabular num-hero text-slate-900">{s.value}</span>
                  </div>
                  <div className="h-[12px] rounded-md bg-slate-100 overflow-hidden">
                    <div
                      className={cn("h-full rounded-md bg-gradient-to-r flex items-center justify-end pr-2", TONE[s.tone].barFrom)}
                      style={{ width: `${s.pct}%` }}
                    >
                      <span className="text-[9px] font-extrabold text-white/90 tabular">{s.pct}%</span>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          </ACard>
        </div>
        <div className="col-span-12 xl:col-span-5 flex flex-col gap-4">
          <ACard title="Finance Efficiency">
            <div className="flex items-baseline gap-2">
              <span className="text-[26px] font-extrabold tabular num-hero glow-emerald text-slate-900 leading-none">
                {f.costPerVerified}
              </span>
              <span className="text-[11px] font-semibold text-slate-500">per verified activity</span>
            </div>
            <p className="text-caption font-semibold text-slate-400 mt-1.5">
              {f.disbursed} disbursed ÷ {f.verifiedActivities} IA-verified activities
            </p>
          </ACard>
          <ACard title="Accountability Watch" subtitle="Money blocked from becoming verified work">
            <div className="grid grid-cols-2 gap-2.5">
              <AcctTile label="Accountability pending" value={f.accountabilityPending} tone="amber" />
              <AcctTile label="NetSuite IDs pending" value={f.netsuitePending} tone="rose" />
              <AcctTile label="Reimbursements due" value={f.reimbursementsDue} tone="sky" />
              <AcctTile label="Balance returns due" value={f.balanceReturnsDue} tone="violet" />
            </div>
            <div className="mt-2.5 rounded-lg bg-rose-50 ring-1 ring-rose-100 px-3 py-2 flex items-center gap-2">
              <AlertTriangle size={13} className="text-rose-500 shrink-0" strokeWidth={2.4} />
              <span className="text-caption font-semibold text-rose-700">
                <span className="font-extrabold tabular">{f.weeksBlocked} staff-weeks</span> blocked by pending accountability.
              </span>
            </div>
          </ACard>
        </div>
      </section>
    </>
  );
}

function AcctTile({ label, value, tone }: { label: string; value: number; tone: Tone }) {
  return (
    <div className={cn("rounded-xl ring-1 px-3 py-2.5", TONE[tone].soft, TONE[tone].ring)}>
      <div className="text-[18px] font-extrabold tabular num-hero text-slate-900 leading-none">{value}</div>
      <div className="text-[9px] font-extrabold uppercase tracking-[0.04em] text-slate-500 mt-1">{label}</div>
    </div>
  );
}

// ════════════════════════════════════════════════════════════════════
//  8 · SUPPORT SIGNALS
// ════════════════════════════════════════════════════════════════════

export function SupportTab() {
  const maxBarrier = Math.max(...barrierRows.map((b) => b.count));
  return (
    <>
      <section className="grid grid-cols-12 gap-4 items-start">
        <div className="col-span-12 xl:col-span-5">
          <ACard title="Field Barriers This Month" subtitle="Categorised from daily debriefs — raw journals stay private">
            <div className="flex flex-col gap-2.5">
              {barrierRows.map((b) => (
                <div key={b.label} className="flex items-center gap-2.5">
                  <span className="w-[112px] shrink-0 text-[11px] font-semibold text-slate-600 truncate">
                    {b.label}
                  </span>
                  <div className="flex-1 h-[8px] rounded-full bg-slate-100 overflow-hidden">
                    <div
                      className={cn(
                        "h-full rounded-full bg-gradient-to-r",
                        b.count > 45 ? TONE.rose.barFrom : b.count > 25 ? TONE.amber.barFrom : TONE.slate.barFrom,
                      )}
                      style={{ width: `${(b.count / maxBarrier) * 100}%` }}
                    />
                  </div>
                  <span className="w-[26px] text-right text-[11px] font-extrabold tabular text-slate-800 shrink-0">
                    {b.count}
                  </span>
                </div>
              ))}
            </div>
            <div className="mt-3 rounded-xl bg-sky-50 ring-1 ring-sky-100 px-3 py-2.5 flex items-start gap-2">
              <CheckCircle2 size={14} className="text-sky-500 shrink-0 mt-0.5" strokeWidth={2.4} />
              <span className="text-caption font-semibold text-sky-800 leading-snug">{barrierInsight}</span>
            </div>
          </ACard>
        </div>

        <div className="col-span-12 xl:col-span-7">
          <ACard
            title="Staff Needing Support"
            subtitle="Signals combined: verified completion, evidence, debrief, accountability"
          >
            <DataTable<StaffRow>
              rowKey={(r) => r.id}
              minWidth={620}
              rows={[...staffRows].sort(
                (a, b) =>
                  ["On Track", "Needs Attention", "Support Needed", "Critical"].indexOf(b.status) -
                  ["On Track", "Needs Attention", "Support Needed", "Critical"].indexOf(a.status),
              )}
              columns={[
                { key: "s", header: "Staff", render: (r) => (
                  <div className="flex items-center gap-2 min-w-0">
                    <Avatar initials={r.initials} size={26} />
                    <span className="text-[11.5px] font-extrabold text-slate-900 truncate">{r.name}</span>
                  </div>
                )},
                { key: "v", header: "Verified", align: "right", render: (r) => (
                  <span className="text-[11px] font-semibold tabular text-slate-600">
                    {Math.round((r.verified / r.planned) * 100)}%
                  </span>
                )},
                { key: "d", header: "Debrief", align: "right", render: (r) => (
                  <span className={cn("text-[11px] font-semibold tabular", r.debriefRate < 70 ? "text-rose-600" : "text-slate-600")}>{r.debriefRate}%</span>
                )},
                { key: "sf", header: "SF Pending", align: "right", render: (r) => (
                  <span className={cn("text-[11px] font-extrabold tabular", r.salesforcePending > 10 ? "text-rose-600" : "text-slate-500")}>{r.salesforcePending}</span>
                )},
                { key: "st", header: "Status", render: (r) => <StatusBadge label={r.status} tone={STAFF_STATUS_TONE[r.status]} /> },
                { key: "a", header: "Recommended Action", render: (r) => (
                  <span className="text-caption font-semibold text-slate-500 inline-flex items-center gap-1">
                    <ArrowRight size={10} className="text-sky-500 shrink-0" />
                    {r.recommendedAction}
                  </span>
                )},
              ]}
            />
          </ACard>
        </div>
      </section>
    </>
  );
}
