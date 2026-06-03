"use client";

// Accountant partner-cluster-payments queue — the finance clearance surface for
// partner-organized cluster activities that IA has already confirmed.
//
// Payment is ONLY available here because IA confirmation has happened: each row
// carries an "IA confirmed" badge and the queue itself is the IA-confirmed,
// unpaid set. The accountant's single action is to clear payment, which calls
// payClusterActivityAction(id) and refreshes the server data.

import { useState, useTransition } from "react";
import { useRouter } from "next/navigation";
import {
  BadgeCheck,
  Banknote,
  CalendarDays,
  MapPin,
  Network,
  ShieldCheck,
  Users,
} from "lucide-react";
import { payClusterActivityAction } from "@/lib/actions/cluster-actions";
import { cn } from "@/lib/utils";

export type PartnerClusterPaymentVM = {
  id: string;
  partner: string;
  clusterName: string;
  district: string;
  label: string;
  date: string;
  salesforceTrainingId?: string;
  total: number;
  iaConfirmedAt?: string;
};

function PaymentRow({ item }: { item: PartnerClusterPaymentVM }) {
  const router = useRouter();
  const [pending, startTransition] = useTransition();
  const [error, setError] = useState<string | null>(null);

  function clearPayment() {
    setError(null);
    startTransition(async () => {
      const res = await payClusterActivityAction(item.id);
      if (res.ok) {
        router.refresh();
        return;
      }
      setError(
        res.reason === "FORBIDDEN"
          ? "Not permitted for your role."
          : res.reason === "FAILED"
            ? res.message
            : "Could not clear payment.",
      );
    });
  }

  return (
    <div
      className={cn(
        "rounded-xl border border-[var(--color-edify-border)] p-3 space-y-2.5",
        "hover:bg-[var(--color-edify-soft)] transition-colors",
      )}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="truncate text-[12.5px] font-extrabold tracking-tight text-[var(--color-edify-text)]">
            {item.partner}
          </div>
          <div className="muted flex flex-wrap items-center gap-x-3 gap-y-0.5 text-[12px]">
            <span className="inline-flex items-center gap-1">
              <Network className="h-3.5 w-3.5" />
              {item.clusterName}
            </span>
            <span className="inline-flex items-center gap-1">
              <MapPin className="h-3.5 w-3.5" />
              {item.district}
            </span>
            <span className="inline-flex items-center gap-1">
              <CalendarDays className="h-3.5 w-3.5" />
              {item.date.slice(0, 10)}
            </span>
          </div>
        </div>
        <span
          className={cn(
            "inline-flex shrink-0 items-center gap-1 rounded-full px-2 py-0.5",
            "border border-emerald-500/30 bg-emerald-500/10",
            "text-[11px] font-bold text-emerald-600 dark:text-emerald-400",
          )}
        >
          <BadgeCheck className="h-3.5 w-3.5" />
          IA confirmed
          {item.iaConfirmedAt ? ` · ${item.iaConfirmedAt.slice(0, 10)}` : ""}
        </span>
      </div>

      <div className="muted flex flex-wrap items-center gap-x-3 gap-y-0.5 text-[12px]">
        <span className="font-bold text-[var(--color-edify-text)]">{item.label}</span>
        {item.salesforceTrainingId ? (
          <span className="tabular inline-flex items-center gap-1">
            <ShieldCheck className="h-3.5 w-3.5" />
            {item.salesforceTrainingId}
          </span>
        ) : null}
        <span className="tabular inline-flex items-center gap-1">
          <Users className="h-3.5 w-3.5" />
          {item.total} attended
        </span>
      </div>

      <div className="flex items-center justify-between gap-3">
        <p className="muted inline-flex items-center gap-1 text-[11px] font-semibold">
          <ShieldCheck className="h-3.5 w-3.5 text-emerald-600 dark:text-emerald-400" />
          IA-confirmed &rarr; cleared to pay
        </p>
        <button
          type="button"
          onClick={clearPayment}
          disabled={pending}
          className={cn(
            "inline-flex shrink-0 items-center gap-1.5 rounded-lg px-3 py-1.5",
            "text-[12px] font-extrabold text-white",
            "bg-[var(--color-edify-primary)] hover:opacity-90",
            "disabled:cursor-not-allowed disabled:opacity-50 transition-opacity",
          )}
        >
          <Banknote className="h-3.5 w-3.5" />
          {pending ? "Clearing…" : "Clear partner payment"}
        </button>
      </div>

      {error ? (
        <p className="text-[11px] font-bold text-red-600 dark:text-red-400">{error}</p>
      ) : null}
    </div>
  );
}

export default function PartnerClusterPaymentsQueue({
  items,
}: {
  items: PartnerClusterPaymentVM[];
}) {
  if (items.length === 0) {
    return (
      <p className="muted text-[12px]">
        No partner cluster payments awaiting clearance.
      </p>
    );
  }

  return (
    <div className="space-y-2">
      {items.map((item) => (
        <PaymentRow key={item.id} item={item} />
      ))}
    </div>
  );
}
