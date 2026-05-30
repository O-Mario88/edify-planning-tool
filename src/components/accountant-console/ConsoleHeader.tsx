"use client";

import { CalendarRange, ChevronDown, Download } from "lucide-react";
import { PageHeader } from "@/components/ui/PageHeader";
import { accountantUser, periodLabel } from "@/lib/accountant-console-mock";

// Accountant console greeting header. The greeting is meaningfully
// different from the system page title ("Finance Console" in
// MobileTopBar), so this passes `showTitleOnMobile` to keep the
// personalised greeting visible on phones + tablets too.
export function ConsoleHeader() {
  return (
    <PageHeader
      title={`Good morning, ${accountantUser.firstName} 👋`}
      subtitle={`Here's your fund overview for ${accountantUser.country}.`}
      showTitleOnMobile
      actions={
        <>
          <button
            type="button"
            className="inline-flex items-center gap-2 h-10 px-3 rounded-xl bg-white ring-1 ring-[var(--color-edify-border)] hover:ring-slate-300 hover:bg-slate-50/60 text-body font-semibold text-slate-700 shadow-[0_1px_2px_rgba(15,23,32,0.04),0_4px_10px_-4px_rgba(15,23,32,0.06)] transition-all"
          >
            <CalendarRange size={13} className="text-slate-500" strokeWidth={2.2} />
            {periodLabel}
            <ChevronDown size={13} className="text-slate-400" />
          </button>
          <button
            type="button"
            className="inline-flex items-center gap-2 h-10 px-4 rounded-xl bg-slate-900 hover:bg-slate-800 active:bg-slate-900 text-white text-body font-extrabold shadow-[0_10px_28px_-12px_rgba(15,23,32,0.55),inset_0_1px_0_rgba(255,255,255,0.08)] transition-colors"
          >
            <Download size={13} strokeWidth={2.4} />
            Export
          </button>
        </>
      }
    />
  );
}
