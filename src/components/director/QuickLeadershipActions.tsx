"use client";

import Link from "next/link";
import {
  Wallet,
  AlertTriangle,
  Database,
  ShieldAlert,
  Target,
  FileText,
  ArrowRight,
  type LucideIcon,
} from "lucide-react";
import { SectionCard } from "@/components/ui/primitives";
import { leadershipActions, type LeadershipActionTile } from "@/lib/director-mock";
import { cn } from "@/lib/utils";

const iconMap: Record<LeadershipActionTile["icon"], LucideIcon> = {
  wallet:        Wallet,
  alertTriangle: AlertTriangle,
  database:      Database,
  shieldAlert:   ShieldAlert,
  target:        Target,
  fileText:      FileText,
};

export function QuickLeadershipActions() {
  return (
    <SectionCard
      icon={<Target size={13} />}
      title="Quick Leadership Actions"
      subtitle="Country Director navigation: review approvals, inspect risk, monitor compliance, open reports."
    >
      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-2 sm:gap-3">
        {leadershipActions.map((a, i) => {
          const Icon = iconMap[a.icon];
          const staggerCls = ["stagger-1","stagger-2","stagger-3","stagger-4","stagger-5","stagger-6"][i] ?? "";
          return (
            <Link
              key={a.key}
              href={a.href}
              className={cn(
                "card card-lift tile-in p-3 flex items-start gap-3 group",
                staggerCls,
              )}
            >
              <span className="w-8 h-8 rounded-md grid place-items-center bg-[var(--color-edify-soft)] text-[var(--color-edify-primary)] shrink-0">
                <Icon size={15} />
              </span>
              <div className="flex-1 min-w-0">
                <div className="text-[12px] font-bold leading-tight">{a.title}</div>
                <div className="text-caption muted mt-0.5 truncate">{a.subtitle}</div>
              </div>
              <ArrowRight
                size={13}
                className="text-[var(--color-edify-muted)] group-hover:text-[var(--color-edify-primary)] mt-1 shrink-0 transition-colors"
              />
            </Link>
          );
        })}
      </div>
    </SectionCard>
  );
}
