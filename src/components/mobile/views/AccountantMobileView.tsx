"use client";

import Link from "next/link";
import {
  Wallet,
  Coins,
  Receipt,
  Banknote,
  ChevronRight,
  type LucideIcon,
} from "lucide-react";
import { MobileShell } from "@/components/mobile/MobileShell";
import { MobileBottomNav } from "@/components/mobile/MobileBottomNav";
import { MobileTopBar } from "@/components/mobile/MobileTopBar";
import {
  fundRequests,
  fundRequestTotal,
  formatUgx,
  type FundRequest,
} from "@/lib/workflow-mock";
import { cn } from "@/lib/utils";
import { shortStatusLabel, fullStatusLabel } from "@/lib/status-labels";

const STATUS_TONE: Record<FundRequest["status"], string> = {
  "Pending Accountant": "bg-amber-100   text-amber-700",
  "Pending Director":   "bg-sky-100     text-sky-700",
  "Pending RVP":        "bg-violet-100  text-violet-700",
  "Disbursed":          "bg-emerald-100 text-emerald-700",
};

export function AccountantMobileView() {
  const pending     = fundRequests.filter((f) => f.status === "Pending Accountant");
  const pendingDir  = fundRequests.filter((f) => f.status === "Pending Director");
  const pendingRvp  = fundRequests.filter((f) => f.status === "Pending RVP");
  const disbursed   = fundRequests.filter((f) => f.status === "Disbursed");

  const pipelineTotal = fundRequests
    .filter((f) => f.status !== "Disbursed")
    .reduce((acc, f) => acc + fundRequestTotal(f), 0);
  const disbursedTotal = disbursed.reduce((acc, f) => acc + fundRequestTotal(f), 0);

  return (
    <MobileShell>
      <MobileTopBar />
      <section
        className="text-white px-4 pt-3 pb-4"
        style={{ backgroundImage: "linear-gradient(180deg, #0e1c2c 0%, #0a1623 100%)" }}
      >
        <h2 className="text-[20px] leading-[1.15] font-extrabold tracking-tight">
          Approve. Disburse. Track.
        </h2>
        <p className="mt-1.5 text-[11.5px] text-white/65 leading-snug">
          {pending.length} pending review · pipeline {formatUgx(pipelineTotal)}
        </p>
      </section>

      <main className="flex-1 px-3 pt-3 pb-4 space-y-3 bg-[var(--color-page)]">
        {/* KPI tiles */}
        <section className="grid grid-cols-2 gap-2">
          <KpiTile Icon={Wallet}   label="Pending Review" value={String(pending.length)}    caption="Awaiting you"      tone="amber"   />
          <KpiTile Icon={Coins}    label="Pending Director" value={String(pendingDir.length)} caption="Forwarded up"     tone="blue"    />
          <KpiTile Icon={Receipt}  label="Pending RVP"     value={String(pendingRvp.length)} caption="Regional approval" tone="violet"  />
          <KpiTile Icon={Banknote} label="Disbursed"       value={String(disbursed.length)}  caption={formatUgx(disbursedTotal)} tone="green" />
        </section>

        {/* Fund request list */}
        <section className="rounded-2xl bg-white border border-[var(--color-edify-border)] shadow-sm">
          <div className="px-3 pt-3 pb-2 flex items-center justify-between">
            <h3 className="text-body font-extrabold tracking-tight">Fund Requests</h3>
            <Link href="/dashboards/accountant" className="text-[11px] font-semibold text-emerald-600 inline-flex items-center gap-0.5 lg:hidden">
              Open full dashboard
              <ChevronRight size={11} />
            </Link>
          </div>
          <ul className="divide-y divide-[var(--color-edify-divider)]">
            {fundRequests.map((fr) => (
              <li key={fr.id} className="px-3 py-2.5 flex items-center gap-3">
                <div className="flex-1 min-w-0">
                  <div className="flex items-baseline justify-between gap-2">
                    <div className="text-body font-extrabold tracking-tight truncate">{fr.district}</div>
                    <span
                      title={fullStatusLabel(fr.status)}
                      className={cn("inline-block px-1.5 py-[2px] rounded-md text-[9.5px] font-extrabold whitespace-nowrap", STATUS_TONE[fr.status])}
                    >
                      {shortStatusLabel(fr.status)}
                    </span>
                  </div>
                  <div className="text-caption muted truncate">
                    {fr.staff} · {fr.month}
                  </div>
                  <div className="text-caption muted truncate">
                    {fr.lineItems.length} line items · submitted {fr.submittedOn}
                  </div>
                </div>
                <div className="text-right shrink-0">
                  <div className="text-body font-extrabold tabular leading-none">
                    {formatUgx(fundRequestTotal(fr))}
                  </div>
                </div>
              </li>
            ))}
          </ul>
        </section>
      </main>

      <MobileBottomNav role="ProgramAccountant" />
    </MobileShell>
  );
}

function KpiTile({
  Icon, label, value, caption, tone,
}: {
  Icon: LucideIcon;
  label: string;
  value: string;
  caption: string;
  tone: "amber" | "blue" | "violet" | "green";
}) {
  const t =
    tone === "amber"  ? "bg-amber-100   text-amber-700" :
    tone === "blue"   ? "bg-sky-100     text-sky-700"   :
    tone === "violet" ? "bg-violet-100  text-violet-700" :
                        "bg-emerald-100 text-emerald-700";
  return (
    <div className="rounded-2xl bg-white border border-[var(--color-edify-border)] shadow-sm p-3">
      <span className={cn("h-8 w-8 rounded-md grid place-items-center", t)}>
        <Icon size={14} />
      </span>
      <div className="text-caption muted font-semibold leading-tight mt-1.5 line-clamp-2">{label}</div>
      <div className="text-[20px] font-extrabold tabular leading-none mt-0.5">{value}</div>
      <div className="text-[10px] muted font-semibold mt-0.5 truncate">{caption}</div>
    </div>
  );
}
