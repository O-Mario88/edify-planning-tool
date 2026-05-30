"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import {
  Search,
  ChevronRight,
  Clock,
  RotateCcw,
  CheckCircle2,
  AlertTriangle,
  GraduationCap,
  Building2,
  Users,
  Handshake,
  Check,
  ArrowLeftCircle,
  UserPlus,
  BarChart3,
  type LucideIcon,
} from "lucide-react";
import { MobileShell } from "@/components/mobile/MobileShell";
import { CplBottomNav } from "@/components/mobile/CplBottomNav";
import { MobileTopBar } from "@/components/mobile/MobileTopBar";
import {
  cplApprovalCounts,
  cplApprovalsList,
  type CplApprovalCategory,
  type CplApprovalItem,
  type CplApprovalStatus,
} from "@/lib/cpl-mock";
import { cn } from "@/lib/utils";
import { useDemoStore } from "@/components/demo/DemoStore";

const TABS: { key: CplApprovalCategory; label: string }[] = [
  { key: "plans",    label: "Plans" },
  { key: "funds",    label: "Funds" },
  { key: "backlogs", label: "Backlogs" },
];

const KIND_ICON: Record<CplApprovalItem["kind"], LucideIcon> = {
  cluster_training: GraduationCap,
  school_visit:     Building2,
  ssa_support:      Users,
  partner_followup: Handshake,
};

const KIND_TONE: Record<CplApprovalItem["kind"], string> = {
  cluster_training: "bg-emerald-100 text-emerald-600",
  school_visit:     "bg-sky-100    text-sky-600",
  ssa_support:      "bg-violet-100 text-violet-600",
  partner_followup: "bg-orange-100 text-orange-600",
};

const STATUS_TONE: Record<CplApprovalStatus, string> = {
  "Awaiting Approval": "bg-amber-100   text-amber-700",
  "Needs Review":      "bg-rose-100    text-rose-600",
  "Ready":             "bg-emerald-100 text-emerald-700",
  "Approved":          "bg-emerald-100 text-emerald-700",
  "Returned":          "bg-rose-100    text-rose-600",
};

export function CplApprovalsView() {
  const [tab, setTab] = useState<CplApprovalCategory>("plans");
  const [query, setQuery] = useState("");
  const { pushToast } = useDemoStore();

  const handleAction = (action: "approve" | "return" | "reassign" | "team-risk") => {
    const config = {
      approve:    { tone: "success" as const, title: "Plan approved",      body: "Selected plan moved to funding workflow." },
      return:     { tone: "warning" as const, title: "Plan returned",      body: "Returned with comments; staff notified." },
      reassign:   { tone: "info" as const,    title: "Reassignment opened", body: "Pick another CCEO or rebalance load." },
      "team-risk":{ tone: "info" as const,    title: "Team risk snapshot",  body: "Opening team risk and pacing view." },
    };
    pushToast(config[action]);
  };

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    return cplApprovalsList.filter(
      (item) =>
        item.category === tab &&
        (q === "" ||
          item.title.toLowerCase().includes(q) ||
          item.owner.toLowerCase().includes(q)),
    );
  }, [tab, query]);

  return (
    <MobileShell>
      <MobileTopBar title="Approvals" backHref="/dashboards/cpl" />
      <div
        className="px-3 pt-3 pb-3 grid grid-cols-3 gap-1.5 text-white"
        style={{ backgroundImage: "linear-gradient(180deg, #0e1c2c 0%, #0a1623 100%)" }}
      >
        {TABS.map((t) => (
          <button
            key={t.key}
            type="button"
            onClick={() => setTab(t.key)}
            className={cn(
              "h-9 rounded-md text-[12px] font-extrabold tracking-tight",
              t.key === tab
                ? "bg-[var(--color-edify-primary)] text-white"
                : "bg-white/[.08] text-white/85 hover:bg-white/[.12]",
            )}
          >
            {t.label}
          </button>
        ))}
      </div>

      <main className="flex-1 px-3 pt-3 pb-4 space-y-3 bg-[var(--color-page)]">
        {/* Status cards (4-col) */}
        <section className="grid grid-cols-4 gap-2">
          <StatusTile Icon={Clock}          tone="amber" value={cplApprovalCounts.waiting}        label="Waiting Approval" />
          <StatusTile Icon={RotateCcw}      tone="rose"  value={cplApprovalCounts.returned}       label="Returned" />
          <StatusTile Icon={CheckCircle2}   tone="green" value={cplApprovalCounts.approvedToday}  label="Approved Today" />
          <StatusTile Icon={AlertTriangle}  tone="rose"  value={cplApprovalCounts.criticalIssues} label="Critical Issues" />
        </section>

        {/* Search */}
        <div className="relative">
          <Search
            size={14}
            className="absolute left-3 top-1/2 -translate-y-1/2 text-[var(--color-edify-muted)]"
          />
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search approvals"
            aria-label="Search approvals"
            className="w-full pl-9 pr-3 h-10 rounded-xl border border-[var(--color-edify-border)] bg-white text-body placeholder:text-[var(--color-edify-muted)] focus:outline-none focus:ring-2 focus:ring-[var(--color-edify-primary)]/30"
          />
        </div>

        {/* Item list */}
        <section className="rounded-2xl bg-white border border-[var(--color-edify-border)] divide-y divide-[var(--color-edify-divider)] shadow-sm">
          {filtered.map((item) => {
            const Icon = KIND_ICON[item.kind];
            return (
              <Link
                key={item.id}
                href="/notifications"
                className="flex items-center gap-3 px-3 py-3 active:bg-[var(--color-edify-soft)]/40"
              >
                <div className={cn("h-10 w-10 rounded-full grid place-items-center shrink-0", KIND_TONE[item.kind])}>
                  <Icon size={18} />
                </div>
                <div className="flex-1 min-w-0">
                  <div className="flex items-start justify-between gap-2">
                    <div className="text-body font-extrabold tracking-tight leading-tight truncate">
                      {item.title}
                    </div>
                    <span className={cn("px-1.5 py-[2px] rounded-md text-[9.5px] font-extrabold whitespace-nowrap", STATUS_TONE[item.status])}>
                      {item.status}
                    </span>
                  </div>
                  <div className="text-caption muted truncate">
                    {item.owner} · {item.ownerRole}
                  </div>
                  <div className="text-caption muted truncate">
                    {item.district}
                  </div>
                  <div className="flex items-center justify-between mt-0.5">
                    <div className="text-caption muted">
                      {item.category === "funds" ? item.plannedRange : `Planned: ${item.plannedRange}`}
                    </div>
                    <div className="text-caption muted">
                      {item.cost !== "—" ? `Cost: ${item.cost}` : ""}
                    </div>
                  </div>
                </div>
                <ChevronRight size={14} className="text-[var(--color-edify-muted)] shrink-0" />
              </Link>
            );
          })}
          {filtered.length === 0 && (
            <div className="px-3 py-6 text-[12px] muted text-center">
              No items in this tab.
            </div>
          )}
        </section>

        {/* Leadership Actions */}
        <section>
          <h3 className="text-[12px] font-extrabold tracking-tight mb-2 px-1">Leadership Actions</h3>
          <div className="grid grid-cols-4 gap-2">
            <ActionTile Icon={Check}           label="Approve Plan"   tone="green"  onClick={() => handleAction("approve")} />
            <ActionTile Icon={ArrowLeftCircle} label="Return"         tone="amber"  onClick={() => handleAction("return")} />
            <ActionTile Icon={UserPlus}        label="Reassign"       tone="blue"   onClick={() => handleAction("reassign")} />
            <ActionTile Icon={BarChart3}       label="View Team Risk" tone="violet" onClick={() => handleAction("team-risk")} />
          </div>
        </section>
      </main>

      <CplBottomNav />
    </MobileShell>
  );
}

function StatusTile({
  Icon,
  value,
  label,
  tone,
}: {
  Icon: LucideIcon;
  value: number;
  label: string;
  tone: "amber" | "rose" | "green";
}) {
  const ring =
    tone === "amber" ? "border-amber-200 text-amber-600" :
    tone === "rose"  ? "border-rose-200  text-rose-600"  :
                       "border-emerald-200 text-emerald-600";
  return (
    <div className="rounded-2xl bg-white border border-[var(--color-edify-border)] p-2 shadow-sm flex flex-col items-center text-center">
      <span className={cn("h-9 w-9 rounded-full border-2 grid place-items-center", ring)}>
        <Icon size={14} />
      </span>
      <div className="text-[20px] font-extrabold tabular leading-none mt-1.5">{value}</div>
      <div className="text-[9.5px] muted font-semibold leading-tight mt-1 line-clamp-2 min-h-[24px]">
        {label}
      </div>
    </div>
  );
}

function ActionTile({
  Icon,
  label,
  tone,
  onClick,
}: {
  Icon: LucideIcon;
  label: string;
  tone: "green" | "amber" | "blue" | "violet";
  onClick?: () => void;
}) {
  const t =
    tone === "green"  ? "border-emerald-200 text-emerald-600 bg-emerald-50" :
    tone === "amber"  ? "border-amber-200   text-amber-600   bg-amber-50"   :
    tone === "blue"   ? "border-sky-200     text-sky-600     bg-sky-50"     :
                        "border-violet-200  text-violet-600  bg-violet-50";
  return (
    <button
      type="button"
      onClick={onClick}
      aria-label={label}
      className="rounded-2xl bg-white border border-[var(--color-edify-border)] p-2 shadow-sm flex flex-col items-center text-center hover:bg-[var(--color-edify-soft)]/40 active:scale-[.98] transition-transform"
    >
      <span className={cn("h-9 w-9 rounded-full border grid place-items-center", t)}>
        <Icon size={14} />
      </span>
      <div className="text-[10px] font-extrabold tracking-tight leading-tight mt-1.5 line-clamp-2 min-h-[24px]">
        {label}
      </div>
    </button>
  );
}
