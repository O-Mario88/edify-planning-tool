// DoneForTodayPartner — psychological closure card at the bottom of
// the Today page. Five-item checklist + progress bar. When all items
// are checked, swaps to a calm "you are clear for today" success state
// so the partner knows they're done.

import { CheckCircle2, Circle, ClipboardCheck, ArrowRight, Sparkles } from "lucide-react";
import { doneForTodayPartner } from "@/lib/partner/partner-today-mock";

export function DoneForTodayPartner() {
  const items = doneForTodayPartner;
  const done = items.filter((i) => i.done).length;
  const total = items.length;
  const remaining = total - done;
  const allDone = remaining === 0;
  const pct = Math.round((done / total) * 100);

  if (allDone) {
    return (
      <section className="rounded-2xl border border-emerald-200 bg-emerald-50 p-5">
        <div className="flex items-start gap-3">
          <span className="grid place-items-center h-12 w-12 rounded-2xl bg-emerald-100 text-emerald-700 shrink-0">
            <Sparkles size={18} />
          </span>
          <div className="flex-1">
            <h3 className="text-[15px] font-extrabold tracking-tight text-emerald-900">
              You are clear for today.
            </h3>
            <p className="text-[12px] text-emerald-800 leading-snug mt-1 max-w-[58ch]">
              All scheduled work, evidence, and corrections due today are complete. Take a moment —
              then review tomorrow's plan so you're ready for the morning.
            </p>
            <div className="mt-3 flex items-center gap-2">
              <button
                type="button"
                className="inline-flex items-center gap-1.5 h-9 px-4 rounded-xl bg-emerald-600 text-white text-[12px] font-extrabold hover:bg-emerald-700"
              >
                Review tomorrow's schedule <ArrowRight size={12} />
              </button>
            </div>
          </div>
        </div>
      </section>
    );
  }

  return (
    <section className="card p-3.5">
      <div className="grid grid-cols-12 gap-4 items-start">
        <div className="col-span-12 md:col-span-9">
          <div className="flex items-baseline justify-between gap-3 mb-3">
            <div>
              <h3 className="text-[15px] font-extrabold tracking-tight">Done for Today</h3>
              <p className="text-[12px] muted mt-0.5">
                You are done when these are all checked. We'll move you to "clear for today" automatically.
              </p>
            </div>
            <span className="text-[12px] font-semibold muted whitespace-nowrap">
              <span className="text-[var(--color-edify-text)] font-extrabold">{done} of {total}</span> completed
            </span>
          </div>

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

        <div className="col-span-12 md:col-span-3 flex flex-col items-center justify-center text-center gap-2 py-2 md:border-l md:border-[var(--color-edify-divider)] md:pl-4">
          <span className="grid place-items-center h-14 w-14 rounded-2xl bg-[var(--color-edify-soft)] text-[var(--color-edify-primary)]">
            <ClipboardCheck size={26} />
          </span>
          <div className="text-body-lg font-extrabold leading-tight">
            {remaining} item{remaining === 1 ? "" : "s"} left
          </div>
          <div className="text-[11px] muted leading-snug">before today is complete.</div>
          <button
            type="button"
            className="mt-1 inline-flex items-center gap-1.5 h-8 px-3 rounded-lg border border-[var(--color-edify-border)] bg-[var(--color-card)] text-[var(--color-edify-text)] text-[11.5px] font-semibold hover:bg-[var(--color-edify-soft)] hover:border-[var(--color-edify-primary)] pressable"
          >
            Review tomorrow
          </button>
        </div>
      </div>
    </section>
  );
}
