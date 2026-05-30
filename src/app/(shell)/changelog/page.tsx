import { Sparkles, Wrench, ShieldCheck, type LucideIcon } from "lucide-react";
import { StubPage } from "@/components/shell/StubPage";

type ChangeKind = "feature" | "improvement" | "security";

type Change = {
  version: string;
  date: string;
  title: string;
  notes: { kind: ChangeKind; text: string }[];
};

const CHANGES: Change[] = [
  {
    version: "v1.4.0",
    date: "May 11, 2026",
    title: "Role-aware navigation + drill-through everywhere",
    notes: [
      { kind: "feature",     text: "/staff, /clusters, /districts, /projects, /fund-requests, /partners, /plans, /debriefs, /trainings, /visits — every table row now drills into a detail page." },
      { kind: "feature",     text: "/map, /messages, /resources, /analytics, /calendar, /help, /search — every sidebar link now resolves to a real page." },
      { kind: "improvement", text: "Role-aware bottom nav: CCEO keeps the FAB, every other role gets a tab set built from their dashboard verbs." },
      { kind: "security",    text: "Cookie-driven currentUser. The sidebar, role gates, and dashboard target all resolve from the session cookie." },
    ],
  },
  {
    version: "v1.3.0",
    date: "May 10, 2026",
    title: "Mobile-first design language",
    notes: [
      { kind: "feature",     text: "Every dashboard wrapped in <ResponsiveDashboard> — desktop tier ≥ 1024 px, tablet 768–1023 with drawered sidebar, mobile < 768." },
      { kind: "feature",     text: "Mobile views for every page (SSA, Core Schools, Field Intelligence, Leaderboard, Special Projects, Leave, Team Targets, School 360)." },
      { kind: "improvement", text: "SSA Performance Trend now annual (was quarterly)." },
    ],
  },
  {
    version: "v1.2.0",
    date: "May 8, 2026",
    title: "Field Intelligence redesign",
    notes: [
      { kind: "feature",     text: "New Today's Field Debrief form with 6 questions + auto-saved indicator." },
      { kind: "feature",     text: "My Weekly Reflection panel pulls top success / top barrier / recommended actions from the engine." },
      { kind: "improvement", text: "Sidebar renames Field Intelligence → Daily Field Debrief." },
    ],
  },
  {
    version: "v1.1.0",
    date: "May 6, 2026",
    title: "Card flexibility",
    notes: [
      { kind: "improvement", text: "items-start on every dashboard grid: cards shrink to content instead of stretching to the row." },
      { kind: "improvement", text: "Tablet (md–lg) sidebar drawers behind the hamburger; desktop (≥ lg) pins persistently." },
    ],
  },
];

const ICON: Record<ChangeKind, LucideIcon> = {
  feature:     Sparkles,
  improvement: Wrench,
  security:    ShieldCheck,
};

const TONE: Record<ChangeKind, string> = {
  feature:     "bg-emerald-100 text-emerald-700",
  improvement: "bg-sky-100     text-sky-700",
  security:    "bg-amber-100   text-amber-700",
};

const LABEL: Record<ChangeKind, string> = {
  feature:     "Feature",
  improvement: "Improvement",
  security:    "Security",
};

export default function ChangelogPage() {
  return (
    <StubPage
      title="Changelog"
      subtitle="Every meaningful release. The platform is in active development across all 8 SSA interventions and 8 roles."
    >
      {CHANGES.map((c) => (
        <section key={c.version} className="card p-3.5">
          <header className="flex items-baseline justify-between mb-2">
            <div>
              <h2 className="text-[15px] font-extrabold tracking-tight">{c.title}</h2>
              <div className="text-[11px] muted">{c.version} · {c.date}</div>
            </div>
          </header>
          <ul className="space-y-1.5">
            {c.notes.map((n, i) => {
              const Icon = ICON[n.kind];
              return (
                <li key={i} className="flex items-start gap-2 text-[12px] leading-snug">
                  <span className={`inline-flex items-center gap-1 px-1.5 py-[2px] rounded-md text-[9.5px] font-extrabold whitespace-nowrap shrink-0 mt-0.5 ${TONE[n.kind]}`}>
                    <Icon size={9} />
                    {LABEL[n.kind]}
                  </span>
                  <span>{n.text}</span>
                </li>
              );
            })}
          </ul>
        </section>
      ))}
    </StubPage>
  );
}
