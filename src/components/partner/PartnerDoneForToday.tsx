// PartnerDoneForToday — the small habit-loop card. Five daily checks
// the partner should clear to stay on track: today's activity done,
// evidence uploaded, report submitted, corrections cleared, tomorrow
// reviewed. Right rail shows a clipboard illustration + the open-item
// count + a single "View My Activities" CTA.

import Link from "next/link";
import { CheckCircle2, Circle, ClipboardCheck } from "lucide-react";
import type { DoneForTodayItem } from "@/lib/partner/partner-dashboard-mock";

export function PartnerDoneForToday({ items }: { items: DoneForTodayItem[] }) {
  const done = items.filter((i) => i.done).length;
  const total = items.length;
  const remaining = total - done;
  const pct = Math.round((done / total) * 100);

  return (
    <section className="card p-3.5">
      <div className="grid grid-cols-12 gap-4 items-start">
        {/* Checklist */}
        <div className="col-span-12 md:col-span-9">
          <div className="flex items-baseline justify-between gap-3 mb-3">
            <div>
              <h3 className="text-[15px] font-extrabold tracking-tight">Done for Today</h3>
              <p className="text-[12px] muted mt-0.5">Complete these items to stay on track each day.</p>
            </div>
            <span className="text-[12px] font-semibold muted whitespace-nowrap">
              <span className="text-[var(--color-edify-text)] font-extrabold">{done} of {total}</span> completed
            </span>
          </div>

          {/* Progress bar */}
          <div className="h-1.5 w-full rounded-full bg-[var(--color-edify-soft)] overflow-hidden">
            <div
              className="h-full bg-emerald-500 transition-all"
              style={{ width: `${pct}%` }}
              aria-hidden
            />
          </div>

          <ul className="mt-4 space-y-2.5">
            {items.map((item) => (
              <li key={item.id} className="flex items-center gap-2.5">
                {item.done ? (
                  <CheckCircle2 size={16} className="text-emerald-500 shrink-0" />
                ) : (
                  <Circle size={16} className="text-[var(--color-edify-muted)] shrink-0" />
                )}
                <span className={`text-body ${item.done ? "text-[var(--color-edify-text)]" : "muted"}`}>
                  {item.label}
                </span>
              </li>
            ))}
          </ul>
        </div>

        {/* Right rail illustration + count + CTA */}
        <div className="col-span-12 md:col-span-3 flex flex-col items-center justify-center text-center gap-2 py-2 md:border-l md:border-[var(--color-edify-divider)] md:pl-4">
          <span className="grid place-items-center h-14 w-14 rounded-2xl bg-[var(--color-edify-soft)] text-[var(--color-edify-primary)]">
            <ClipboardCheck size={26} />
          </span>
          <div className="text-[13.5px] font-extrabold leading-tight">
            {remaining} item{remaining === 1 ? "" : "s"} left
          </div>
          <div className="text-[11px] muted leading-snug">before today is complete.</div>
          <Link
            href="#my-activities"
            className="mt-1 inline-flex items-center gap-1.5 h-8 px-3 rounded-lg border border-[var(--color-edify-border)] bg-white text-[var(--color-edify-text)] text-[11.5px] font-semibold hover:bg-[var(--color-edify-soft)]/60"
          >
            View My Activities
          </Link>
        </div>
      </div>
    </section>
  );
}
