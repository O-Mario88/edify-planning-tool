// PartnerAssignedSchools — a horizontal row of 4 school cards under
// "This Week's Assigned Schools". Each card surfaces the school's
// identity, the support need driving the planned activity, the SSA
// weak area context, what's planned, when it's due, when it was last
// supported, and a deep-link to the school page.

import Link from "next/link";
import { ArrowRight, School } from "lucide-react";
import type { PartnerAssignedSchool } from "@/lib/partner/partner-dashboard-mock";

export function PartnerAssignedSchools({ schools }: { schools: PartnerAssignedSchool[] }) {
  return (
    <section>
      <div className="flex items-center justify-between mb-3">
        <div>
          <h2 className="text-[15px] font-extrabold tracking-tight">This Week's Assigned Schools</h2>
          <p className="text-[12px] muted mt-0.5">Schools that require your support this week.</p>
        </div>
        <Link
          href="#all-schools"
          className="text-[12px] font-semibold text-[var(--color-edify-primary)] hover:underline inline-flex items-center gap-1"
        >
          View All schools <ArrowRight size={11} />
        </Link>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3">
        {schools.map((s) => (
          <SchoolCard key={s.id} school={s} />
        ))}
      </div>
    </section>
  );
}

function SchoolCard({ school: s }: { school: PartnerAssignedSchool }) {
  return (
    <article className="card p-3.5 flex flex-col">
      <header className="flex items-start gap-2.5">
        <span className="grid place-items-center h-9 w-9 rounded-lg bg-[var(--color-edify-soft)] text-[var(--color-edify-primary)] shrink-0">
          <School size={15} />
        </span>
        <div className="min-w-0">
          <h3 className="text-[13px] font-extrabold tracking-tight truncate">{s.name}</h3>
          <p className="text-[11px] muted leading-tight mt-0.5">
            {s.district} · {s.subCounty}
          </p>
          <p className="text-caption muted leading-tight">Parish: {s.parish}</p>
        </div>
      </header>

      <div className="mt-3 space-y-2 text-[12px]">
        <Field label="Support Need" value={s.supportNeed} />
        <Field label="SSA Weak Area" value={s.ssaWeakArea} />
        <Field label="Planned Activity" value={s.plannedActivity} />
        <div className="grid grid-cols-2 gap-2 pt-1">
          <DateRow label="Due Date" value={s.dueDate} />
          <DateRow label="Last Support" value={s.lastSupport} />
        </div>
      </div>

      <Link
        href={`/schools#${s.id}`}
        className="mt-4 inline-flex items-center justify-center gap-1.5 h-8 px-3 rounded-md border border-[var(--color-edify-border)] bg-white text-[var(--color-edify-text)] text-[12px] font-semibold hover:bg-[var(--color-edify-soft)]/60 transition-colors"
      >
        View School
      </Link>
    </article>
  );
}

function Field({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div className="text-[10px] uppercase tracking-wide font-bold muted">{label}</div>
      <div className="text-[12px] font-semibold text-[var(--color-edify-text)] leading-tight mt-0.5">{value}</div>
    </div>
  );
}

function DateRow({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div className="text-[10px] uppercase tracking-wide font-bold muted">{label}</div>
      <div className="text-[11.5px] font-semibold text-[var(--color-edify-text)] leading-tight mt-0.5">{value}</div>
    </div>
  );
}
