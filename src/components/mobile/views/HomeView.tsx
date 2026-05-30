import Link from "next/link";
import {
  ChevronDown,
  Calendar,
  ArrowUpRight,
  AlertTriangle,
  MapPinOff,
  GraduationCap,
  ShieldOff,
  ClipboardList,
  Map,
  CheckCircle2,
  Database,
  ChevronRight,
  type LucideIcon,
} from "lucide-react";
import { MobileShell } from "@/components/mobile/MobileShell";
import { MobileBottomNav } from "@/components/mobile/MobileBottomNav";
import { MobileTopBar } from "@/components/mobile/MobileTopBar";
import { MiniSpark } from "@/components/mobile/MiniSpark";
import {
  mobileUser,
  homeHero,
  monthSelector,
  monthlyPerformance,
  schoolStats,
  thisWeekStats,
  priorityAttention,
  homeQuickActions,
  type PriorityAttention,
  type QuickAction,
} from "@/lib/mobile-mock";
import { cn } from "@/lib/utils";

const ATTENTION_ICON: Record<PriorityAttention["icon"], LucideIcon> = {
  alertTriangle:    AlertTriangle,
  mapPinOff:        MapPinOff,
  graduationCapOff: GraduationCap,
  shieldOff:        ShieldOff,
};
const ATTENTION_TONE: Record<PriorityAttention["tone"], string> = {
  rose:   "bg-rose-50 text-rose-600",
  amber:  "bg-amber-50 text-amber-700",
  violet: "bg-violet-50 text-violet-600",
  blue:   "bg-blue-50 text-blue-600",
};

const QA_ICON: Record<QuickAction["icon"], LucideIcon> = {
  plan:     ClipboardList,
  route:    Map,
  logVisit: CheckCircle2,
  data:     Database,
};

export function HomeView() {
  return (
    <MobileShell>
      <MobileTopBar notificationsCount={mobileUser.notificationCount} />
      {/* Hero copy under the top bar */}
      <section
        className="text-white px-4 pt-3 pb-5"
        style={{ backgroundImage: "linear-gradient(180deg, #0e1c2c 0%, #0a1623 100%)" }}
      >
        <div className="text-body text-white/85">
          {mobileUser.greeting}, {mobileUser.firstName} <span aria-hidden>👋</span>
        </div>
        <h1 className="mt-2 text-[26px] leading-[1.1] font-extrabold tracking-tight">
          {homeHero.title}
        </h1>
        <p className="mt-1.5 text-body text-white/70 leading-snug">{homeHero.subtitle}</p>
      </section>

      <main className="flex-1 px-3 py-4 space-y-4">
        {/* Month selector */}
        <button
          type="button"
          className="w-full rounded-2xl bg-white border border-[var(--color-edify-border)] p-3 flex items-center gap-3 shadow-sm"
        >
          <span className="w-9 h-9 rounded-lg bg-emerald-50 grid place-items-center text-emerald-600">
            <Calendar size={16} />
          </span>
          <div className="leading-tight text-left flex-1">
            <div className="text-[15px] font-extrabold tracking-tight">{monthSelector.label}</div>
            <div className="text-[11px] muted">{monthSelector.hint}</div>
          </div>
          <ChevronDown size={16} className="text-[var(--color-edify-muted)]" />
        </button>

        {/* Monthly Performance */}
        <section className="rounded-2xl bg-white border border-[var(--color-edify-border)] shadow-sm p-3">
          <div className="flex items-center justify-between mb-3 px-1">
            <h3 className="text-body-lg font-extrabold tracking-tight">Monthly Performance</h3>
            <Link href="/dashboards/cpl" className="text-[12px] font-semibold text-emerald-600">View All</Link>
          </div>
          <div className="grid grid-cols-2 gap-2.5">
            {monthlyPerformance.map((m) => (
              <MetricTile
                key={m.key}
                label={m.label}
                value={m.value}
                trendDelta={m.trend.delta}
                trendTone={m.trend.tone}
                spark={m.spark}
              />
            ))}
          </div>
          <div className="grid grid-cols-2 gap-2.5 mt-2.5">
            {schoolStats.map((m) => (
              <MetricTile
                key={m.key}
                label={m.label}
                value={m.value}
                trendDelta={m.trend.delta}
                trendTone={m.trend.tone}
                spark={m.spark}
              />
            ))}
          </div>
        </section>

        {/* This Week */}
        <section className="rounded-2xl bg-white border border-[var(--color-edify-border)] shadow-sm p-3">
          <div className="flex items-center justify-between mb-3 px-1">
            <h3 className="text-body-lg font-extrabold tracking-tight">
              This Week <span className="muted font-medium">({thisWeekStats.weekLabel})</span>
            </h3>
            <Link href="/my-plan" className="text-[12px] font-semibold text-emerald-600">View Week</Link>
          </div>
          <div className="grid grid-cols-3 gap-2">
            {thisWeekStats.tiles.map((t) => (
              <div
                key={t.key}
                className="rounded-xl bg-[var(--color-edify-soft)]/60 border border-[var(--color-edify-border)] p-2 text-center"
              >
                <div className="text-caption muted font-semibold leading-tight line-clamp-2 min-h-[28px] mt-1">
                  {t.label}
                </div>
                <div className="text-[12px] muted mt-1">Tap to plan</div>
              </div>
            ))}
          </div>
        </section>

        {/* Priority Attention */}
        <section className="rounded-2xl bg-white border border-[var(--color-edify-border)] shadow-sm p-3">
          <div className="flex items-center justify-between mb-2 px-1">
            <h3 className="text-body-lg font-extrabold tracking-tight">Priority Attention</h3>
            <Link href="/schools" className="text-[12px] font-semibold text-emerald-600">View All</Link>
          </div>
          <div className="divide-y divide-[var(--color-edify-divider)]">
            {priorityAttention.map((p) => {
              const Icon = ATTENTION_ICON[p.icon];
              return (
                <Link
                  key={p.key}
                  href="/schools"
                  className="flex items-center gap-3 py-2.5 active:bg-[var(--color-edify-soft)]/40 -mx-1 px-1 rounded-md"
                >
                  <span className={cn("w-7 h-7 rounded-md grid place-items-center shrink-0", ATTENTION_TONE[p.tone])}>
                    <Icon size={14} />
                  </span>
                  <div className="flex-1 text-[13px] font-semibold leading-tight">{p.label}</div>
                  <span className="text-body-lg font-extrabold tabular shrink-0">{p.count}</span>
                  <ChevronRight size={14} className="text-[var(--color-edify-muted)] shrink-0" />
                </Link>
              );
            })}
          </div>
        </section>

        {/* Quick Actions */}
        <section className="rounded-2xl bg-white border border-[var(--color-edify-border)] shadow-sm p-3">
          <h3 className="text-body-lg font-extrabold tracking-tight mb-3 px-1">Quick Actions</h3>
          <div className="grid grid-cols-4 gap-2">
            {homeQuickActions.map((a) => {
              const Icon = QA_ICON[a.icon];
              return (
                <Link
                  key={a.key}
                  href={a.href}
                  className="rounded-xl border border-[var(--color-edify-border)] p-2.5 flex flex-col items-center text-center hover:bg-[var(--color-edify-soft)]/40"
                >
                  <span className="w-9 h-9 rounded-full bg-emerald-50 text-emerald-600 grid place-items-center mb-1.5">
                    <Icon size={16} />
                  </span>
                  <div className="text-caption font-bold leading-tight line-clamp-2 min-h-[28px]">
                    {a.label}
                  </div>
                </Link>
              );
            })}
          </div>
        </section>
      </main>

      <MobileBottomNav />
    </MobileShell>
  );
}

function MetricTile({
  label,
  value,
  trendDelta,
  trendTone,
  spark,
}: {
  label: string;
  value: string;
  trendDelta: string;
  trendTone: "up" | "down";
  spark: { seed: number; trend: "up" | "down" };
}) {
  const cls =
    trendTone === "up" ? "text-emerald-600" : "text-rose-600";
  return (
    <div className="rounded-xl border border-[var(--color-edify-border)] bg-white p-2.5 overflow-hidden">
      <div className="text-caption muted font-semibold leading-tight line-clamp-2 min-h-[26px]">
        {label}
      </div>
      <div className="flex items-baseline justify-between mt-1.5">
        <span className="text-[20px] font-extrabold tabular leading-none truncate">{value}</span>
        <span className={cn("text-caption font-extrabold inline-flex items-center gap-0.5 shrink-0", cls)}>
          <ArrowUpRight size={10} />
          {trendDelta} vs Apr
        </span>
      </div>
      <div className="mt-1">
        <MiniSpark seed={spark.seed} trend={spark.trend} color={trendTone === "up" ? "#10b981" : "#ef4444"} />
      </div>
    </div>
  );
}
