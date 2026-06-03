// IA Cluster Salesforce-Confirmation Queue — the action surface where Impact
// Assessment confirms completed cluster activities in Salesforce (or returns
// them for correction). Consumes serialisable VMs built server-side from the
// stable cluster engine's clusterActivitiesAwaitingIa(); never touches the
// engine directly. All mutations route through the role-gated server actions.

"use client";

import { useState, useTransition } from "react";
import { useRouter } from "next/navigation";
import {
  AlertTriangle,
  CalendarClock,
  CheckCircle2,
  FileCheck2,
  FileText,
  ListChecks,
  Undo2,
  Users,
} from "lucide-react";
import {
  iaConfirmClusterActivityAction,
  returnClusterActivityAction,
} from "@/lib/actions/cluster-actions";
import { cn } from "@/lib/utils";

export type IaClusterConfirmationVM = {
  id: string;
  label: string;
  clusterName: string;
  district: string;
  date: string;
  organizer: "partner" | "edify";
  managedByPartnerName?: string;
  completedBy?: string;
  salesforceTrainingId?: string;
  salesforceIdValid: boolean;
  teachers: number;
  leaders: number;
  other: number;
  total: number;
  hasMinutes: boolean;
  hasResolutions: boolean;
  attendanceFileName?: string;
  nextMeetingDate?: string;
};

function Flag({
  ok,
  label,
  icon,
}: {
  ok: boolean;
  label: string;
  icon: React.ReactNode;
}) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[11px] font-bold",
        ok
          ? "border-emerald-500/30 bg-emerald-500/10 text-emerald-600 dark:text-emerald-400"
          : "border-[var(--color-edify-border)] text-[var(--color-edify-muted)]",
      )}
    >
      {icon}
      {label}
    </span>
  );
}

function Row({ item }: { item: IaClusterConfirmationVM }) {
  const router = useRouter();
  const [pending, startTransition] = useTransition();
  const [error, setError] = useState<string | null>(null);
  const [returning, setReturning] = useState(false);
  const [reason, setReason] = useState("");

  function showError(reasonCode: string, message?: string) {
    setError(
      reasonCode === "FORBIDDEN"
        ? "Not permitted for your role."
        : message ?? "Action failed. Please try again.",
    );
  }

  function confirm() {
    setError(null);
    startTransition(async () => {
      const res = await iaConfirmClusterActivityAction(item.id);
      if (res.ok) {
        router.refresh();
      } else {
        showError(res.reason, "message" in res ? res.message : undefined);
      }
    });
  }

  function submitReturn() {
    const trimmed = reason.trim();
    if (!trimmed) {
      setError("Enter a reason for the correction.");
      return;
    }
    setError(null);
    startTransition(async () => {
      const res = await returnClusterActivityAction(item.id, trimmed);
      if (res.ok) {
        router.refresh();
      } else {
        showError(res.reason, "message" in res ? res.message : undefined);
      }
    });
  }

  return (
    <div className="rounded-xl border border-[var(--color-edify-border)] p-3 space-y-2.5">
      {/* Header: cluster + meeting label, managed-by badge */}
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="truncate text-[12.5px] font-extrabold tracking-tight text-[var(--color-edify-text)]">
            {item.clusterName}
          </div>
          <div className="muted truncate text-[12px]">
            {item.label} · {item.district} · {item.date.slice(0, 10)}
            {item.completedBy ? ` · ${item.completedBy}` : ""}
          </div>
        </div>
        <span
          className={cn(
            "shrink-0 rounded-full border px-2 py-0.5 text-[11px] font-bold",
            item.organizer === "partner"
              ? "border-[var(--color-edify-primary)] text-[var(--color-edify-primary)]"
              : "border-[var(--color-edify-border)] text-[var(--color-edify-text)]",
          )}
        >
          {item.organizer === "partner"
            ? `Partner${item.managedByPartnerName ? ` · ${item.managedByPartnerName}` : ""}`
            : "Edify"}
        </span>
      </div>

      {/* Salesforce TS- id — the primary thing IA must check */}
      <div
        className={cn(
          "flex items-center gap-2 rounded-lg border px-2.5 py-1.5",
          item.salesforceIdValid
            ? "border-[var(--color-edify-border)]"
            : "border-rose-500/40 bg-rose-500/10",
        )}
      >
        {item.salesforceIdValid ? (
          <FileCheck2 className="h-3.5 w-3.5 shrink-0 text-[var(--color-edify-muted)]" />
        ) : (
          <AlertTriangle className="h-3.5 w-3.5 shrink-0 text-rose-500" />
        )}
        <span className="tabular text-[12px] font-extrabold text-[var(--color-edify-text)]">
          {item.salesforceTrainingId || "No Salesforce id"}
        </span>
        {!item.salesforceIdValid && (
          <span className="text-[11px] font-bold text-rose-600 dark:text-rose-400">
            Must be a TS- training id
          </span>
        )}
      </div>

      {/* Attendance breakdown */}
      <div className="flex items-center gap-2 text-[12px] text-[var(--color-edify-text)]">
        <Users className="h-3.5 w-3.5 text-[var(--color-edify-muted)]" />
        <span className="tabular font-extrabold">{item.total}</span>
        <span className="muted">
          total · {item.teachers} teachers · {item.leaders} leaders
          {item.other ? ` · ${item.other} other` : ""}
        </span>
      </div>

      {/* Evidence completeness flags */}
      <div className="flex flex-wrap items-center gap-1.5">
        <Flag
          ok={item.hasMinutes}
          label="Minutes"
          icon={<FileText className="h-3 w-3" />}
        />
        <Flag
          ok={item.hasResolutions}
          label="Resolutions"
          icon={<ListChecks className="h-3 w-3" />}
        />
        <Flag
          ok={Boolean(item.attendanceFileName)}
          label="Attendance form"
          icon={<FileCheck2 className="h-3 w-3" />}
        />
        {item.nextMeetingDate && (
          <span className="inline-flex items-center gap-1 rounded-full border border-[var(--color-edify-border)] px-2 py-0.5 text-[11px] font-bold text-[var(--color-edify-text)]">
            <CalendarClock className="h-3 w-3 text-[var(--color-edify-muted)]" />
            Next {item.nextMeetingDate.slice(0, 10)}
          </span>
        )}
      </div>

      {error && (
        <p className="text-[11px] font-bold text-rose-600 dark:text-rose-400">
          {error}
        </p>
      )}

      {/* Actions */}
      {returning ? (
        <div className="space-y-2">
          <input
            type="text"
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            placeholder="Reason for correction"
            disabled={pending}
            className={cn(
              "w-full rounded-lg border border-[var(--color-edify-border)] bg-transparent",
              "px-2.5 py-1.5 text-[12px] text-[var(--color-edify-text)]",
              "placeholder:text-[var(--color-edify-muted)] focus:outline-none",
              "focus:border-[var(--color-edify-primary)]",
            )}
          />
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={submitReturn}
              disabled={pending}
              className={cn(
                "inline-flex items-center gap-1.5 rounded-lg border border-[var(--color-edify-border)]",
                "px-2.5 py-1.5 text-[12px] font-bold text-[var(--color-edify-text)]",
                "hover:bg-[var(--color-edify-soft)] disabled:opacity-50",
              )}
            >
              <Undo2 className="h-3.5 w-3.5" />
              Send back
            </button>
            <button
              type="button"
              onClick={() => {
                setReturning(false);
                setReason("");
                setError(null);
              }}
              disabled={pending}
              className="text-[12px] font-bold text-[var(--color-edify-muted)] hover:text-[var(--color-edify-text)] disabled:opacity-50"
            >
              Cancel
            </button>
          </div>
        </div>
      ) : (
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={confirm}
            disabled={pending}
            className={cn(
              "inline-flex items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-[12px] font-bold",
              "bg-[var(--color-edify-primary)] text-white hover:opacity-90 disabled:opacity-50",
            )}
          >
            <CheckCircle2 className="h-3.5 w-3.5" />
            Confirm in Salesforce
          </button>
          <button
            type="button"
            onClick={() => {
              setReturning(true);
              setError(null);
            }}
            disabled={pending}
            className={cn(
              "inline-flex items-center gap-1.5 rounded-lg border border-[var(--color-edify-border)]",
              "px-2.5 py-1.5 text-[12px] font-bold text-[var(--color-edify-text)]",
              "hover:bg-[var(--color-edify-soft)] disabled:opacity-50",
            )}
          >
            <Undo2 className="h-3.5 w-3.5" />
            Return for correction
          </button>
        </div>
      )}
    </div>
  );
}

export default function IaClusterConfirmationQueue({
  items,
}: {
  items: IaClusterConfirmationVM[];
}) {
  return (
    <section className="card rounded-2xl p-4 space-y-3">
      <div className="flex items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <span className="text-[var(--color-edify-primary)]">
            <FileCheck2 className="h-4 w-4" />
          </span>
          <h2 className="text-[16px] font-extrabold tracking-tight text-[var(--color-edify-text)]">
            Awaiting Salesforce confirmation
          </h2>
        </div>
        <span className="tabular text-[12.5px] font-extrabold text-[var(--color-edify-text)]">
          {items.length}
        </span>
      </div>
      {items.length === 0 ? (
        <p className="muted text-[12px]">
          No cluster activities awaiting Salesforce confirmation.
        </p>
      ) : (
        <div className="space-y-2">
          {items.map((item) => (
            <Row key={item.id} item={item} />
          ))}
        </div>
      )}
    </section>
  );
}
