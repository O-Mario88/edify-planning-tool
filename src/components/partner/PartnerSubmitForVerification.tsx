"use client";

// Partner "Submit for verification" — the control that closes the partner cycle.
// After a partner uploads evidence for a delivered activity, this submits it
// with its Salesforce ID, which calls the live backend complete() and moves the
// activity to awaiting_ia_verification — so the IA sees it in the verification
// queue (with the uploaded evidence) and can confirm it onward to payment.
// Without this the partner cycle dead-ended after upload. No mock.

import { useState } from "react";
import { useRouter } from "next/navigation";
import { Send, Loader2 } from "lucide-react";
import { csrfHeaders } from "@/lib/csrf-client";
import { EmptyState } from "@/components/ui/DataStates";

export type SubmitActivity = { id: string; title: string; kind: "visit" | "training" };

export function PartnerSubmitForVerification({ activities }: { activities: SubmitActivity[] }) {
  const router = useRouter();
  const [sfIds, setSfIds] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState<string | null>(null);
  const [errs, setErrs] = useState<Record<string, string>>({});

  const submit = async (a: SubmitActivity) => {
    const sf = (sfIds[a.id] ?? "").trim();
    setBusy(a.id); setErrs((e) => ({ ...e, [a.id]: "" }));
    try {
      const res = await fetch(`/api/activities/${a.id}/complete`, {
        method: "POST", credentials: "include", headers: { "Content-Type": "application/json", ...csrfHeaders() },
        body: JSON.stringify({ salesforceId: sf }),
      });
      const j = await res.json();
      if (j.live) router.refresh();
      else setErrs((e) => ({ ...e, [a.id]: j.error || "Submission was rejected." }));
    } catch { setErrs((e) => ({ ...e, [a.id]: "Could not reach the server." })); }
    setBusy(null);
  };

  return (
    <section className="card p-3.5">
      <header className="flex items-center justify-between gap-2 mb-2.5">
        <h2 className="text-[13px] font-extrabold tracking-tight inline-flex items-center gap-1.5"><Send size={14} /> Submit delivered work for verification</h2>
        <span className="inline-flex items-center gap-1 rounded-full bg-[var(--color-edify-soft)] text-[var(--color-edify-primary)] px-2 py-0.5 text-[10px] font-bold border border-[var(--color-edify-border)]">Live</span>
      </header>
      {activities.length === 0 ? (
        <EmptyState compact title="Nothing to submit yet" message="Upload evidence for a delivered activity above, then submit it here with its Salesforce ID — it goes to the IA for verification." />
      ) : (
        <ul className="space-y-2">
          {activities.map((a) => (
            <li key={a.id} className="rounded-lg border border-[var(--color-edify-border)] p-2.5">
              <p className="text-[12px] font-bold mb-1.5">{a.title}</p>
              <div className="flex items-center gap-2">
                <input
                  value={sfIds[a.id] ?? ""}
                  onChange={(e) => setSfIds((s) => ({ ...s, [a.id]: e.target.value }))}
                  placeholder={a.kind === "visit" ? "SV-XXXXX (Salesforce visit id)" : "TS-XXXXX (Salesforce id)"}
                  className="flex-1 h-9 px-2.5 rounded-lg border border-[var(--color-edify-border)] bg-[var(--surface-1)] text-[12px] font-semibold"
                />
                <button
                  disabled={busy === a.id || !(sfIds[a.id] ?? "").trim()}
                  onClick={() => submit(a)}
                  className="h-9 px-3.5 inline-flex items-center gap-1.5 rounded-lg bg-[var(--color-edify-primary)] hover:bg-[var(--color-edify-dark)] text-white text-[11.5px] font-bold disabled:opacity-50 whitespace-nowrap"
                >
                  {busy === a.id ? <Loader2 size={13} className="animate-spin" /> : <Send size={13} />} Submit
                </button>
              </div>
              {errs[a.id] && <p className="text-[11px] text-rose-600 font-semibold mt-1">{errs[a.id]}</p>}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
