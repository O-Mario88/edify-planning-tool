// Project planning-gap lists on the CCEO/PL planning page (spec §17).
// One collapsible card per non-empty gap category (the list IS the detail-
// heavy content, per the collapsible-card rule). Server component — the
// collapse behaviour lives in CollapsibleCard's client island.

import Link from "next/link";
import { Sparkles, ArrowRight, CheckCircle2 } from "lucide-react";
import { CollapsibleCard } from "@/components/ui/CollapsibleCard";
import { SectionHeader } from "@/components/ui/SectionHeader";
import type { ProjectGapCategory } from "@/lib/projects/project-planning-gaps";

export function ProjectPlanningGaps({ categories }: { categories: ProjectGapCategory[] }) {
  const nonEmpty = categories.filter((c) => c.items.length > 0);
  const total = categories.reduce((a, c) => a + c.items.length, 0);

  return (
    <section className="space-y-2.5">
      <SectionHeader
        eyebrow="Special Projects"
        title="Project follow-up"
        description="Project-specific work for your schools — separate from the SSA gap boards above."
        icon={<Sparkles size={14} />}
      />

      {total === 0 ? (
        <div className="card rounded-2xl p-6 text-center">
          <CheckCircle2 size={20} className="mx-auto text-emerald-600" />
          <p className="mt-1.5 text-[12.5px] font-bold">No open project follow-ups.</p>
          <p className="text-[11.5px] muted">Every project school in your scope is up to date.</p>
        </div>
      ) : (
        nonEmpty.map((cat) => (
          <CollapsibleCard
            key={cat.key}
            id={`project-gap-${cat.key}`}
            tier="operational"
            title={cat.label}
            defaultCollapsed
            meta={
              <span className="inline-flex items-center gap-1.5 text-[11px] font-bold">
                <span className="px-1.5 py-[1px] rounded bg-[var(--color-edify-primary)]/10 text-[var(--color-edify-primary)] tabular">{cat.items.length}</span>
                <span className="muted">{cat.action}</span>
              </span>
            }
          >
            <ul className="divide-y divide-[var(--color-edify-divider)]">
              {cat.items.map((it) => (
                <li key={it.key} className="py-2 flex items-center justify-between gap-3">
                  <div className="min-w-0">
                    <Link href={`/schools/${it.schoolId}`} className="text-[12.5px] font-bold hover:text-[var(--color-edify-primary)] hover:underline">{it.schoolName}</Link>
                    <span className="muted text-[11px] ml-1">#{it.schoolId} · {it.district}</span>
                    <div className="text-[11px] muted truncate">{it.projectShortName} · {it.detail}</div>
                  </div>
                  <Link href={it.href} className="shrink-0 inline-flex items-center gap-1 h-7 px-2.5 rounded-lg border border-[var(--color-edify-border)] bg-white text-[11.5px] font-semibold hover:bg-[var(--color-edify-soft)]/60">
                    {cat.action} <ArrowRight size={11} />
                  </Link>
                </li>
              ))}
            </ul>
          </CollapsibleCard>
        ))
      )}
    </section>
  );
}
