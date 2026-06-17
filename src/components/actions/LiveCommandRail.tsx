import Link from "next/link";
import { AlertTriangle, ArrowRight, CheckCircle2, Inbox } from "lucide-react";
import { getCurrentUser } from "@/lib/auth";
import { fetchCommandCenterToday } from "@/lib/api/surfaces";
import { InsufficientData } from "@/components/ui/InsufficientData";

// The live "what must I do next" rail — role-scoped action items computed by the
// backend command-center from REAL state (cluster/SSA gaps, owned activity steps,
// IA/accountant queues). Replaces the mock role-action-engine board in production.

const DOT: Record<string, string> = {
  critical: "bg-rose-500",
  high: "bg-amber-500",
  medium: "bg-sky-500",
};

export async function LiveCommandRail() {
  const user = await getCurrentUser();
  const res = await fetchCommandCenterToday(user);
  if (!res.live) return <InsufficientData surface="your action feed" />;
  const { summary, groups } = res.data;

  if (summary.total === 0) {
    return (
      <div className="card p-6 text-center">
        <CheckCircle2 className="mx-auto text-emerald-500" size={22} />
        <p className="mt-2 text-[13px] font-extrabold tracking-tight">You&apos;re all clear</p>
        <p className="text-[11.5px] muted mt-0.5">No actions need you right now — new work appears here automatically.</p>
      </div>
    );
  }

  return (
    <div className="space-y-3">
      <div className="flex items-center gap-2 text-[11.5px]">
        <Inbox size={13} className="text-[var(--color-edify-primary)]" />
        <span className="font-extrabold tracking-tight">Your next actions</span>
        <span className="muted">
          {summary.critical} red · {summary.action} to do · {summary.attention} watch
        </span>
      </div>
      {groups.map((g) => (
        <section key={g.key} className="card p-3.5">
          <header className="flex items-baseline justify-between mb-2">
            <h3 className="text-[12.5px] font-extrabold tracking-tight inline-flex items-center gap-1.5">
              {g.key === "critical" ? <AlertTriangle size={13} className="text-rose-600" /> : null}
              {g.label}
            </h3>
            <span className="text-caption muted">{g.items.length}</span>
          </header>
          <ul className="space-y-2">
            {g.items.map((it) => (
              <li key={it.id} className="rounded-xl border border-[var(--color-edify-border)] p-2.5 flex items-start gap-2.5 bg-[var(--color-edify-soft)]/20">
                <span className={`mt-1.5 w-1.5 h-1.5 rounded-full shrink-0 ${DOT[it.priority] ?? DOT.medium}`} />
                <div className="min-w-0 flex-1">
                  <div className="text-[12.5px] font-extrabold tracking-tight">
                    {it.title}{it.count ? ` (${it.count})` : ""}
                  </div>
                  <div className="text-[11px] muted leading-snug mt-0.5">{it.reason}</div>
                </div>
                <Link
                  href={it.action.href}
                  className="shrink-0 inline-flex items-center gap-1 h-7 px-2.5 rounded-lg bg-[var(--color-edify-primary)] text-white text-[11px] font-semibold hover:opacity-90"
                >
                  {it.action.label} <ArrowRight size={11} />
                </Link>
              </li>
            ))}
          </ul>
        </section>
      ))}
    </div>
  );
}
