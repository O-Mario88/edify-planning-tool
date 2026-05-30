"use client";

// PartnerHeader — client-side wrapper around PageHeader so the partner
// route (a server component) can pass icon-typed filters without
// tripping the "Functions cannot be passed to Client Components"
// boundary. All chrome — title + subtitle + filters + Filters button
// + identity — flows through here.

import { Calendar, Filter } from "lucide-react";
import { PageHeader } from "@/components/ui/PageHeader";

export function PartnerHeader() {
  return (
    <PageHeader
      title="Partner"
      subtitle="Schedule assigned school support, submit evidence, track confirmation, and follow payment progress."
      filters={[
        { Icon: Calendar, label: "FY 2026" },
        { Icon: Calendar, label: "Week 3 · May 12 - May 18" },
      ]}
      actions={
        <button
          type="button"
          className="inline-flex items-center gap-1.5 h-10 px-3 rounded-xl bg-white border border-[var(--color-edify-border)] text-body font-semibold hover:bg-[var(--color-edify-soft)]/40"
        >
          <Filter size={13} className="text-[var(--color-edify-muted)]" /> Filters
        </button>
      }
    />
  );
}
