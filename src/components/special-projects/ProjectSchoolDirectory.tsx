"use client";

// Project-grouped school directory body: category tabs + search over a stack
// of ProjectSchoolCards. Search is project-scoped — it filters which cards
// show and which schools show inside each card.

import { useMemo, useState } from "react";
import { Search, Sparkles, FilterX } from "lucide-react";
import { cn } from "@/lib/utils";
import { ProjectSchoolCard } from "./ProjectSchoolCard";
import type { ProjectCardVM } from "@/lib/projects/project-school-directory";
import type { ProjectCategory } from "@/lib/special-projects-mock";

type TabKey = "all" | ProjectCategory;

const TABS: { key: TabKey; label: string }[] = [
  { key: "all", label: "All Projects" },
  { key: "intervention_specific", label: "Intervention-Specific" },
  { key: "pilot", label: "Pilot" },
  { key: "selective_limited", label: "Selective" },
];

function cardMatchesQuery(card: ProjectCardVM, q: string): boolean {
  if (!q) return true;
  if (card.project.projectName.toLowerCase().includes(q)) return true;
  if (card.project.primaryInterventionId.toLowerCase().includes(q)) return true;
  if (card.project.assignedPartnerName?.toLowerCase().includes(q)) return true;
  return card.schools.some((s) =>
    s.schoolName.toLowerCase().includes(q) ||
    s.schoolId.toLowerCase().includes(q) ||
    s.district.toLowerCase().includes(q) ||
    (s.cluster?.toLowerCase().includes(q) ?? false) ||
    (s.accountOwner?.toLowerCase().includes(q) ?? false),
  );
}

export function ProjectSchoolDirectory({
  cards, userRole,
}: {
  cards: ProjectCardVM[];
  userRole: string;
}) {
  const [tab, setTab] = useState<TabKey>("all");
  const [query, setQuery] = useState("");
  const q = query.trim().toLowerCase();

  const counts = useMemo(() => {
    const c: Record<TabKey, number> = { all: cards.length, intervention_specific: 0, pilot: 0, selective_limited: 0 };
    for (const card of cards) c[card.project.projectCategory as ProjectCategory] += 1;
    return c;
  }, [cards]);

  const visible = useMemo(
    () => cards.filter((c) => (tab === "all" || c.project.projectCategory === tab) && cardMatchesQuery(c, q)),
    [cards, tab, q],
  );

  return (
    <div className="space-y-3">
      {/* Tabs + search */}
      <div className="flex items-center justify-between gap-3 flex-wrap">
        <div className="flex items-center gap-1 p-1 rounded-lg bg-[var(--color-edify-soft)]/50">
          {TABS.map((t) => (
            <button
              key={t.key}
              type="button"
              onClick={() => setTab(t.key)}
              className={cn(
                "h-8 px-3 rounded-md text-[12px] font-bold transition-colors inline-flex items-center gap-1.5",
                tab === t.key ? "bg-white shadow-sm text-[var(--color-edify-text)]" : "text-[var(--color-edify-muted)] hover:text-[var(--color-edify-text)]",
              )}
            >
              {t.label}
              <span className="px-1 rounded bg-[var(--color-edify-primary)]/10 text-[var(--color-edify-primary)] text-[10px] tabular">{counts[t.key]}</span>
            </button>
          ))}
        </div>
        <div className="relative flex-1 min-w-[220px] max-w-sm">
          <Search size={14} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-[var(--color-edify-muted)]" />
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search project, school, ID, district, owner…"
            className="w-full h-9 pl-8 pr-3 text-[12.5px] rounded-lg bg-white border border-[var(--color-edify-border)] outline-none focus:outline-2 focus:outline-[var(--color-edify-primary)]"
          />
        </div>
      </div>

      {/* Cards */}
      {visible.length === 0 ? (
        cards.length === 0 ? (
          <div className="card rounded-2xl p-10 text-center">
            <Sparkles size={22} className="mx-auto text-[var(--color-edify-muted)]" />
            <p className="mt-2 text-[13px] font-bold">No schools have been assigned to projects yet.</p>
            <p className="text-[12px] muted mt-0.5">Assign schools to a project from the School Directory to see them grouped here.</p>
          </div>
        ) : (
          <div className="card rounded-2xl p-10 text-center">
            <FilterX size={22} className="mx-auto text-[var(--color-edify-muted)]" />
            <p className="mt-2 text-[13px] font-bold">No project schools match the selected filters.</p>
            <button type="button" onClick={() => { setTab("all"); setQuery(""); }} className="mt-2 text-[12px] font-semibold text-[var(--color-edify-primary)] hover:underline">
              Reset filters
            </button>
          </div>
        )
      ) : (
        visible.map((card) => (
          <ProjectSchoolCard key={card.project.projectId} card={card} userRole={userRole} query={q} />
        ))
      )}
    </div>
  );
}
