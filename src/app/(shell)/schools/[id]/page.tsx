import { notFound } from "next/navigation";
import Link from "next/link";
import {
  Building2,
  MapPin,
  Phone,
  User,
  Users,
  CalendarDays,
  Sparkles,
  ShieldCheck,
  CalendarCheck,
  ChevronLeft,
  TrendingUp,
} from "lucide-react";
import { AppShell } from "@/components/app/AppShell";
import { SectionCard, KpiCard, StatusBadge, ProgressRing } from "@/components/ui/primitives";
import { ActionButton } from "@/components/ui/ActionButton";
import { schoolsCatalog, salesforceMatches, validVisitRules } from "@/lib/workflow-mock";
import { ResponsiveDashboard } from "@/components/mobile/ResponsiveDashboard";
import { SchoolDetailMobileView } from "@/components/mobile/views/SchoolDetailMobileView";
import { SchoolPartnerJourney, sampleJourneyForHope } from "@/components/partner/SchoolPartnerJourney";

export default async function School360({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const s = schoolsCatalog.find((x) => x.id === id);
  if (!s) return notFound();

  // Stub history derived from the school
  const ssaHistory = [
    { period: "2024 Q3", score: Math.max(10, s.ssaScore - 14) },
    { period: "2024 Q4", score: Math.max(10, s.ssaScore - 8) },
    { period: "2025 Q1", score: Math.max(10, s.ssaScore - 3) },
    { period: "2025 Q2", score: s.ssaScore },
  ];

  const planned = [
    { kind: "In-School Coaching", window: "May / Wk 1", status: "Active Todo" as const },
    { kind: "SSA Follow-Up",      window: "May / Wk 2", status: "Scheduled" as const },
    { kind: "Cluster Training",   window: "May 06",     status: "Approved" as const },
  ];
  const completed = [
    { kind: "School Visit",        window: "Apr 24", sfId: "SFA-002711", validVisit: "Yes" as const },
    { kind: "In-School Coaching",  window: "Apr 17", sfId: "SFA-002702", validVisit: "Yes" as const },
    { kind: "SSA Support",         window: "Apr 10", sfId: "SFA-002692", validVisit: "No"  as const },
  ];

  return (
    <ResponsiveDashboard mobile={<SchoolDetailMobileView school={s} />} desktop={
    <AppShell
      role="CCEO"
      title="School 360"
      subtitle="Operational profile, SSA history, planned vs completed activities, and verification trail."
      filters={["financialYear", "month", "region"]}
    >
      <div className="-mt-2">
        <Link
          href="/schools"
          className="inline-flex items-center gap-1 text-[12px] muted hover:text-[var(--color-edify-text)]"
        >
          <ChevronLeft size={12} />
          Back to Schools
        </Link>
      </div>

      {/* Identity card */}
      <SectionCard
        title={s.name}
        subtitle={`${s.cluster} · ${s.district} District`}
        icon={<Building2 size={13} />}
        actions={
          <div className="flex items-center gap-2">
            <ActionButton
              label="Update Visit"
              className="btn btn-sm"
              toast={{
                tone: "info",
                title: `Visit log opened — ${s.name}`,
                body: "Capture date, evidence, and Salesforce ID to complete the visit.",
              }}
            />
            <ActionButton
              label="Schedule Activity"
              className="btn btn-sm btn-primary"
              toast={{
                tone: "success",
                title: `Activity scheduler opened`,
                body: `Pick a week and activity type for ${s.name}.`,
              }}
            />
          </div>
        }
      >
        <div className="grid grid-cols-12 gap-3">
          <div className="col-span-12 md:col-span-3">
            <div className="label-up">Status</div>
            <div className="mt-1 flex items-center gap-2">
              <StatusBadge tone={s.status === "Active" ? "green" : s.status === "Becoming Inactive" ? "amber" : "red"}>
                {s.status}
              </StatusBadge>
              <StatusBadge tone={s.segment === "Core" ? "edify" : "blue"}>{s.segment}</StatusBadge>
            </div>
          </div>
          <div className="col-span-12 md:col-span-3">
            <div className="label-up">Assigned CCEO</div>
            <div className="text-[13px] font-bold mt-0.5 flex items-center gap-1.5">
              <User size={12} />
              {s.cceo}
            </div>
          </div>
          <div className="col-span-12 md:col-span-3">
            <div className="label-up">Assigned Partner</div>
            <div className="text-[13px] font-bold mt-0.5 flex items-center gap-1.5">
              <Users size={12} />
              {s.partner}
            </div>
          </div>
          <div className="col-span-12 md:col-span-3">
            <div className="label-up">Contact</div>
            <div className="text-[13px] font-bold mt-0.5 flex items-center gap-1.5">
              <Phone size={12} />
              +254 712 345 678
            </div>
          </div>

          <div className="col-span-12 md:col-span-3">
            <div className="label-up">Gateway Status</div>
            <div className="text-body font-bold mt-0.5">Onboarded · 12 Mar 2024</div>
          </div>
          <div className="col-span-12 md:col-span-3">
            <div className="label-up">Coordinates</div>
            <div className="text-body font-bold mt-0.5 flex items-center gap-1.5">
              <MapPin size={12} />
              {s.dataQuality === "Needs Coordinates" ? "Missing — needs update" : "0.3398° N, 32.5817° E"}
            </div>
          </div>
          <div className="col-span-12 md:col-span-3">
            <div className="label-up">Risk Level</div>
            <div className="text-body font-bold mt-0.5">
              <StatusBadge tone={s.ssaScore < 35 ? "red" : s.ssaScore < 55 ? "amber" : "green"}>
                {s.ssaScore < 35 ? "High" : s.ssaScore < 55 ? "Medium" : "Low"}
              </StatusBadge>
            </div>
          </div>
          <div className="col-span-12 md:col-span-3">
            <div className="label-up">Special Projects</div>
            <div className="text-body font-bold mt-0.5 flex items-center gap-1.5">
              <Sparkles size={12} />
              EdTech · CCSEL
            </div>
          </div>
        </div>
      </SectionCard>

      {/* KPI strip */}
      <section className="grid grid-cols-6 gap-3">
        <KpiCard label="SSA Score"        value={`${s.ssaScore}%`} caption="Latest" icon={<TrendingUp size={16} />} iconTone={s.ssaScore < 35 ? "red" : s.ssaScore < 55 ? "amber" : "green"} />
        <KpiCard label="Valid Visits YTD" value="6"                caption="Counts toward target" icon={<ShieldCheck size={16} />} iconTone="green" />
        <KpiCard label="Trainings YTD"    value="2"                caption="Cluster + In-School" icon={<Users size={16} />} iconTone="edify" />
        <KpiCard label="Last Visit"       value={s.lastVisit}      caption="On record"           icon={<CalendarCheck size={16} />} iconTone="edify" />
        <KpiCard label="MSC Stories"      value="3"                caption="Most Significant Change" icon={<Sparkles size={16} />} iconTone="violet" />
        <KpiCard label="Enrolment"        value="412"              caption="Latest update"       icon={<Users size={16} />} iconTone="edify" />
      </section>

      {/* Partner support journey — closes the workflow loop:
          every partner activity for this school is threaded into the
          school's own timeline so the work is understood as school
          improvement, not just partner payment. */}
      <SchoolPartnerJourney {...sampleJourneyForHope()} />

      {/* SSA history + planned/completed */}
      <section className="grid grid-cols-12 gap-4">
        <div className="col-span-12 md:col-span-5">
          <SectionCard icon={<TrendingUp size={13} />} title="SSA History" subtitle="Recommendations always start from SSA performance.">
            <div className="space-y-2">
              {ssaHistory.map((h) => (
                <div key={h.period} className="flex items-center gap-3">
                  <div className="text-[12px] font-semibold w-[80px]">{h.period}</div>
                  <div className="flex-1">
                    <div className="pill-row">
                      <span style={{ width: `${h.score}%`, background: h.score < 35 ? "var(--color-danger)" : h.score < 55 ? "var(--color-edify-orange)" : "var(--color-success)" }} />
                    </div>
                  </div>
                  <div className="text-body tabular font-extrabold w-[40px] text-right">{h.score}%</div>
                </div>
              ))}
            </div>
            <div className="mt-3 pt-3 border-t border-[#eef2f4] text-[12px]">
              <div className="muted">Weakest intervention</div>
              <div className="font-bold mt-0.5">{s.weakestIntervention}</div>
              <div className="muted mt-2">Recommended next</div>
              <div className="font-bold mt-0.5">{s.recommended}</div>
            </div>
          </SectionCard>
        </div>

        <div className="col-span-12 md:col-span-7 space-y-4">
          <SectionCard icon={<CalendarDays size={13} />} title="Planned Activities" subtitle="Active todos and approved/scheduled work.">
            <table className="w-full dtable">
              <thead>
                <tr>
                  <th scope="col" className="text-left">Activity</th>
                  <th scope="col" className="text-left">Window</th>
                  <th scope="col" className="text-left">Status</th>
                  <th scope="col" className="text-right">Action</th>
                </tr>
              </thead>
              <tbody>
                {planned.map((p, i) => (
                  <tr key={i}>
                    <td className="text-body font-semibold">{p.kind}</td>
                    <td className="text-[12px] muted">{p.window}</td>
                    <td>
                      <StatusBadge tone={p.status === "Approved" ? "green" : "blue"}>{p.status}</StatusBadge>
                    </td>
                    <td className="text-right">
                      <ActionButton
                        label="Open"
                        ariaLabel={`Open ${p.kind} (${p.window})`}
                        className="btn btn-sm"
                        toast={{
                          tone: "info",
                          title: `Opening ${p.kind}`,
                          body: `${p.window} · ${p.status}`,
                        }}
                      />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </SectionCard>

          <SectionCard icon={<ShieldCheck size={13} />} title="Completed Activities · Verification Trail" subtitle="Salesforce IDs and valid-visit outcomes.">
            <table className="w-full dtable">
              <thead>
                <tr>
                  <th scope="col" className="text-left">Activity</th>
                  <th scope="col" className="text-left">Window</th>
                  <th scope="col" className="text-left">SFA ID</th>
                  <th scope="col" className="text-left">Valid Visit</th>
                </tr>
              </thead>
              <tbody>
                {completed.map((c, i) => (
                  <tr key={i}>
                    <td className="text-body font-semibold">{c.kind}</td>
                    <td className="text-[12px] muted">{c.window}</td>
                    <td className="text-[12px] tabular">{c.sfId}</td>
                    <td>
                      <StatusBadge tone={c.validVisit === "Yes" ? "green" : "red"}>{c.validVisit}</StatusBadge>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </SectionCard>
        </div>
      </section>

      {/* Salesforce + Valid visit + Health rings */}
      <section className="grid grid-cols-12 gap-4">
        <div className="col-span-12 md:col-span-7">
          <SectionCard icon={<CalendarCheck size={13} />} title="Salesforce Activity for this School" subtitle="Smart match against planned windows.">
            <table className="w-full dtable">
              <thead>
                <tr>
                  <th scope="col" className="text-left">Activity</th>
                  <th scope="col" className="text-left">Match</th>
                  <th scope="col" className="text-left">SFA ID</th>
                  <th scope="col" className="text-right">Days Open</th>
                </tr>
              </thead>
              <tbody>
                {salesforceMatches.slice(0, 4).map((r) => (
                  <tr key={r.id}>
                    <td className="text-body font-semibold">{r.activity}</td>
                    <td>
                      <StatusBadge tone={r.matchState === "Strong match" ? "green" : r.matchState === "No match" ? "red" : "amber"}>
                        {r.matchState}
                      </StatusBadge>
                    </td>
                    <td className="text-[12px] tabular">{r.sfId ?? "—"}</td>
                    <td className="text-right tabular text-[12px]">{r.daysOpen}d</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </SectionCard>
        </div>
        <div className="col-span-12 md:col-span-5">
          <SectionCard icon={<ShieldCheck size={13} />} title="Visit Quality" subtitle="Why visits count or do not count for this school.">
            <ul className="space-y-1.5">
              {validVisitRules.map((r) => (
                <li
                  key={r.kind}
                  className="flex items-center gap-2 text-[12px] py-1 px-1.5 rounded-md hover:bg-[var(--color-edify-soft)]/50"
                >
                  <span
                    className={`w-2.5 h-2.5 rounded-full ${r.counts ? "bg-[var(--color-success)]" : "bg-[var(--color-danger)]"}`}
                  />
                  <span className="font-semibold">{r.kind}</span>
                  <span className="ml-auto muted">{r.counts ? "Counts" : "Does not count"}</span>
                </li>
              ))}
            </ul>
            <div className="mt-3 pt-3 border-t border-[#eef2f4] grid grid-cols-3 gap-2 text-center">
              {[
                { l: "Verified", v: 92 },
                { l: "Logged", v: 88 },
                { l: "Evidence", v: 84 },
              ].map((x) => (
                <div key={x.l}>
                  <ProgressRing pct={x.v} size={56} stroke={5} label={`${x.v}%`} />
                  <div className="text-caption muted mt-1 font-semibold">{x.l}</div>
                </div>
              ))}
            </div>
          </SectionCard>
        </div>
      </section>
    </AppShell>
    } />
  );
}
