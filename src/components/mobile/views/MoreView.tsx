"use client";

import Link from "next/link";
import {
  ChevronRight,
  CheckSquare,
  Database,
  Map,
  ClipboardList,
  CalendarRange,
  ShieldCheck,
  FileText,
  Settings,
  Brain,
  Activity,
  Star,
  type LucideIcon,
} from "lucide-react";
import { MobileShell } from "@/components/mobile/MobileShell";
import { MobileBottomNav } from "@/components/mobile/MobileBottomNav";
import { MobileTopBar } from "@/components/mobile/MobileTopBar";
import { todayHeader, todaysTaskCounts } from "@/lib/mobile-mock";
import { sfQueueCounts } from "@/lib/mobile-mock";
import { cn } from "@/lib/utils";

type MenuItem = {
  key: string;
  label: string;
  caption?: string;
  href: string;
  Icon: LucideIcon;
  iconBg: string;
  iconText: string;
  rightSlot?: React.ReactNode;
};

type MenuGroup = {
  title: string;
  items: MenuItem[];
};

export function MoreView() {
  // Today's Tasks gets its own hero card at the top — it's the primary
  // entry on this More menu.
  const remaining = todaysTaskCounts.planned + todaysTaskCounts.inProgress;

  const groups: MenuGroup[] = [
    {
      title: "Field Work",
      items: [
        {
          key: "queue",
          label: "Salesforce Queue",
          caption: `${sfQueueCounts.awaiting} awaiting · ${sfQueueCounts.submitted} submitted`,
          href: "/queue",
          Icon: Database,
          iconBg: "bg-amber-100",
          iconText: "text-amber-700",
        },
        {
          key: "route",
          label: "Smart Route",
          caption: "Plan today's stops",
          href: "/route",
          Icon: Map,
          iconBg: "bg-sky-100",
          iconText: "text-sky-700",
        },
        {
          key: "plan",
          label: "Monthly Plan",
          caption: "Build & submit your plan",
          href: "/my-plan",
          Icon: ClipboardList,
          iconBg: "bg-emerald-100",
          iconText: "text-emerald-700",
        },
      ],
    },
    {
      title: "Performance",
      items: [
        {
          key: "ssa",
          label: "SSA Performance",
          caption: "Cluster scores & trends",
          href: "/ssa",
          Icon: Activity,
          iconBg: "bg-violet-100",
          iconText: "text-violet-700",
        },
        {
          key: "core_schools",
          label: "Core Schools",
          caption: "Pipeline & onboarding",
          href: "/core-schools",
          Icon: Star,
          iconBg: "bg-yellow-100",
          iconText: "text-yellow-700",
        },
        {
          key: "field_intel",
          label: "Daily Field Debrief",
          caption: "Daily debrief",
          href: "/field-intelligence",
          Icon: Brain,
          iconBg: "bg-blue-100",
          iconText: "text-blue-700",
        },
      ],
    },
    {
      title: "Operations",
      items: [
        {
          key: "leave",
          label: "Leave & Holidays",
          caption: "Time off & calendar",
          href: "/leave",
          Icon: CalendarRange,
          iconBg: "bg-rose-100",
          iconText: "text-rose-700",
        },
        {
          key: "reports",
          label: "Reports",
          caption: "Exports & summaries",
          href: "/reports",
          Icon: FileText,
          iconBg: "bg-slate-100",
          iconText: "text-slate-700",
        },
      ],
    },
    {
      title: "Account",
      items: [
        {
          key: "admin",
          label: "Administration",
          caption: "Manage roles & data",
          href: "#admin",
          Icon: ShieldCheck,
          iconBg: "bg-slate-100",
          iconText: "text-slate-700",
        },
        {
          key: "settings",
          label: "Settings",
          caption: "Preferences & sign out",
          href: "/settings",
          Icon: Settings,
          iconBg: "bg-slate-100",
          iconText: "text-slate-700",
        },
      ],
    },
  ];

  return (
    <MobileShell>
      <MobileTopBar title="More" />

      <main className="flex-1 px-3 pt-3 pb-4 space-y-3 bg-[var(--color-page)]">
        {/* Today's Tasks hero — primary call to action on this menu */}
        <Link
          href="/today"
          className="block rounded-2xl text-white p-4 active:opacity-90"
          style={{ backgroundImage: "linear-gradient(135deg, #0e1c2c 0%, #1a3148 100%)" }}
        >
          <div className="flex items-center gap-3">
            <span className="h-11 w-11 rounded-xl bg-white/[.10] grid place-items-center shrink-0">
              <CheckSquare size={20} />
            </span>
            <div className="flex-1 min-w-0">
              <div className="text-caption text-white/65 font-semibold tracking-wide uppercase">
                {todayHeader.dateLabel}
              </div>
              <div className="text-[16px] font-extrabold tracking-tight leading-tight">
                Today&apos;s Tasks
              </div>
              <div className="text-[11.5px] text-white/75 mt-0.5">
                {remaining > 0
                  ? `${remaining} remaining · ${todaysTaskCounts.completed} done`
                  : "All clear for today"}
              </div>
            </div>
            <ChevronRight size={18} className="text-white/70 shrink-0" />
          </div>

          <div className="mt-3 grid grid-cols-4 gap-2">
            <TodayChip label="Planned"     value={todaysTaskCounts.planned} />
            <TodayChip label="In Progress" value={todaysTaskCounts.inProgress} />
            <TodayChip label="Completed"   value={todaysTaskCounts.completed} />
            <TodayChip label="Overdue"     value={todaysTaskCounts.overdue} tone="rose" />
          </div>
        </Link>

        {/* Grouped menu items */}
        {groups.map((g) => (
          <section key={g.title}>
            <h3 className="text-[10px] font-extrabold uppercase tracking-wider muted px-2 mb-1.5">
              {g.title}
            </h3>
            <div className="rounded-2xl bg-white border border-[var(--color-edify-border)] divide-y divide-[var(--color-edify-divider)] shadow-sm">
              {g.items.map((item) => (
                <Link
                  key={item.key}
                  href={item.href}
                  className="flex items-center gap-3 px-3 py-3 active:bg-[var(--color-edify-soft)]/40"
                >
                  <span className={cn("h-9 w-9 rounded-md grid place-items-center shrink-0", item.iconBg, item.iconText)}>
                    <item.Icon size={16} />
                  </span>
                  <div className="flex-1 min-w-0">
                    <div className="text-body font-extrabold tracking-tight">{item.label}</div>
                    {item.caption && (
                      <div className="text-caption muted truncate">{item.caption}</div>
                    )}
                  </div>
                  {item.rightSlot}
                  <ChevronRight size={14} className="text-[var(--color-edify-muted)] shrink-0" />
                </Link>
              ))}
            </div>
          </section>
        ))}
      </main>

      <MobileBottomNav />
    </MobileShell>
  );
}

function TodayChip({
  label,
  value,
  tone = "neutral",
}: {
  label: string;
  value: number;
  tone?: "neutral" | "rose";
}) {
  return (
    <div
      className={cn(
        "rounded-xl border p-2 text-center",
        tone === "rose"
          ? "bg-rose-500/15 border-rose-300/30"
          : "bg-white/[.08] border-white/10",
      )}
    >
      <div className="text-[18px] font-extrabold tabular leading-none">{value}</div>
      <div className="text-[9.5px] text-white/70 mt-1">{label}</div>
    </div>
  );
}
