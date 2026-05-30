"use client";

import { ShieldCheck, Info } from "lucide-react";
import { PageHeader } from "@/components/ui/PageHeader";
import { leaveHeader } from "@/lib/leave-mock";

// LeaveHeader — thin adapter over the canonical <PageHeader>. The
// "Planning Engine Active" pill is page-specific brand content, so it
// rides into the actions slot; everything else (title, subtitle,
// breadcrumbs, search, bell, avatar) comes from PageHeader.
export function LeaveHeader() {
  return (
    <PageHeader
      title={leaveHeader.title}
      subtitle={leaveHeader.subtitle}
      actions={
        <span className="hidden lg:inline-flex items-center gap-2 h-9 pl-2.5 pr-3 rounded-full border border-emerald-500/30 bg-emerald-50 text-emerald-700 text-[12px] font-bold">
          <ShieldCheck size={13} className="text-emerald-600" />
          <span className="w-1.5 h-1.5 rounded-full bg-emerald-500 inline-block" />
          Planning Engine Active
          <Info size={12} className="text-emerald-700/70" />
        </span>
      }
    />
  );
}
