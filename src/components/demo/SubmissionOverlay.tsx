"use client";

import { useDemoStore } from "@/components/demo/DemoStore";
import { CheckCircle2, RotateCcw, Edit3, Send, ClipboardCheck } from "lucide-react";
import { cn } from "@/lib/utils";

// Renders the live demo overlay (status changes + audit appends + amendments
// captured during this demo session) inside the submission detail page.
// Server-rendered base data stays untouched; this just layers on top.

export function SubmissionOverlayBanner({ submissionId }: { submissionId: string }) {
  const { state, reset } = useDemoStore();
  const o = state.submissions[submissionId];
  if (!o) return null;
  const events = o.auditAppend ?? [];
  return (
    <section className="card p-3.5 border-emerald-200 bg-emerald-50/40">
      <header className="flex items-baseline justify-between mb-2">
        <h2 className="text-body-lg font-extrabold tracking-tight inline-flex items-center gap-2">
          <CheckCircle2 size={14} className="text-emerald-700" />
          Live demo overlay
        </h2>
        <button
          type="button"
          onClick={reset}
          className="text-caption font-semibold text-rose-700 hover:underline"
        >
          Reset demo state
        </button>
      </header>
      <p className="text-[11.5px] muted mb-2">
        These actions were performed in this demo session. The server-rendered base data is unchanged; production
        wires the same state to the database.
      </p>
      {o.status && (
        <div className="text-[11.5px] mb-2">
          <span className="font-extrabold">Live status: </span>
          <span className="inline-flex items-center px-1.5 py-[2px] rounded-md text-[10px] font-extrabold bg-emerald-100 text-emerald-700">
            {o.status}
          </span>
        </div>
      )}
      <ul className="space-y-1.5">
        {events.map((e, i) => {
          const Icon =
            e.action === "Approved"   ? CheckCircle2 :
            e.action === "Returned"   ? RotateCcw    :
            e.action === "Amended"    ? Edit3        :
            e.action === "Submitted to RVP" ? Send  :
                                        ClipboardCheck;
          const tone =
            e.action === "Approved"   ? "bg-emerald-100 text-emerald-700" :
            e.action === "Returned"   ? "bg-rose-100    text-rose-700"    :
            e.action === "Amended"    ? "bg-amber-100   text-amber-700"   :
                                        "bg-sky-100     text-sky-700";
          return (
            <li key={i} className="flex items-start gap-3 text-[12px]">
              <span className={cn("h-7 w-7 rounded-full grid place-items-center shrink-0", tone)}>
                <Icon size={12} />
              </span>
              <div className="min-w-0 flex-1">
                <div>
                  <span className="font-extrabold">{e.actor}</span> <span className="muted">({e.role})</span> <span>· {e.action}</span>
                  {e.previousStatus && (
                    <span className="muted ml-1">[{e.previousStatus} → {e.newStatus}]</span>
                  )}
                </div>
                {e.comment && <div className="text-caption muted italic">&quot;{e.comment}&quot;</div>}
              </div>
              <div className="text-caption muted shrink-0">{e.at}</div>
            </li>
          );
        })}
      </ul>
    </section>
  );
}
