"use client";

// LiveCompose — a real, backend-wired message composer. Loads the recipients
// the caller may address from /api/messages/recipients (role-scoped on the
// backend) and POSTs to /api/messages (send) which starts a context-tagged
// thread + notifies the recipient. Replaces the legacy mock MessageCompose,
// whose recipient picker used mock-directory emails that don't map to backend
// user ids. Send -> redirect to /messages (the bell/drawer shows the live thread
// for the recipient).

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { Send, Loader2, CheckCircle2 } from "lucide-react";
import { EmptyState, ErrorState, LoadingState } from "@/components/ui/DataStates";
import { csrfHeaders } from "@/lib/csrf-client";

type Recipient = { id: string; name: string; role: string };

// Context is required by the backend — every message ties to a workflow object.
const CONTEXTS: { value: string; label: string }[] = [
  { value: "general", label: "General" },
  { value: "school", label: "School" },
  { value: "cluster", label: "Cluster" },
  { value: "activity", label: "Activity" },
  { value: "fund_request", label: "Fund request" },
  { value: "evidence", label: "Evidence" },
  { value: "staff_performance", label: "Staff performance" },
  { value: "leave", label: "Leave" },
  { value: "daily_debrief", label: "Daily debrief" },
];

const roleLabel = (r: string) => r.replace(/([a-z])([A-Z])/g, "$1 $2");

export function LiveCompose({ backHref = "/messages" }: { backHref?: string }) {
  const router = useRouter();
  const [recipients, setRecipients] = useState<Recipient[] | null>(null);
  const [loadErr, setLoadErr] = useState<string | null>(null);

  const [recipientId, setRecipientId] = useState("");
  const [contextType, setContextType] = useState("general");
  const [subject, setSubject] = useState("");
  const [body, setBody] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [sent, setSent] = useState(false);

  useEffect(() => {
    fetch("/api/messages/recipients", { credentials: "include" })
      .then((r) => r.json())
      .then((j) => {
        if (j.live) { setRecipients(j.recipients as Recipient[]); setRecipientId((j.recipients?.[0]?.id) ?? ""); }
        else setLoadErr(j.error || "Could not load recipients");
      })
      .catch(() => setLoadErr("Could not reach the server"));
  }, []);

  const canSend = recipientId && body.trim().length > 0 && !busy;

  const send = async () => {
    setBusy(true); setErr(null);
    try {
      const res = await fetch("/api/messages", {
        method: "POST", credentials: "include", headers: { "Content-Type": "application/json", ...csrfHeaders() },
        body: JSON.stringify({ recipientId, contextType, subject: subject.trim() || undefined, body: body.trim() }),
      });
      const j = await res.json();
      if (j.live) { setSent(true); setTimeout(() => router.push(backHref), 700); }
      else setErr(j.error || "The message was rejected.");
    } catch { setErr("Could not reach the server."); }
    setBusy(false);
  };

  if (loadErr) return <div className="max-w-[720px]"><ErrorState message={loadErr} /></div>;
  if (!recipients) return <div className="max-w-[720px]"><LoadingState /></div>;
  if (recipients.length === 0) return <div className="max-w-[720px]"><EmptyState title="No recipients" message="You don't currently have anyone you can message." /></div>;

  return (
    <div className="max-w-[720px] space-y-3.5">
      <div className="card p-4 space-y-3">
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
          <label className="block">
            <span className="block text-[10.5px] font-bold uppercase tracking-wide muted mb-1">To</span>
            <select value={recipientId} onChange={(e) => setRecipientId(e.target.value)} className="w-full h-10 px-2.5 rounded-lg border border-[var(--color-edify-border)] bg-[var(--surface-1)] text-[13px] font-semibold">
              {recipients.map((r) => <option key={r.id} value={r.id}>{r.name} · {roleLabel(r.role)}</option>)}
            </select>
          </label>
          <label className="block">
            <span className="block text-[10.5px] font-bold uppercase tracking-wide muted mb-1">Context (required)</span>
            <select value={contextType} onChange={(e) => setContextType(e.target.value)} className="w-full h-10 px-2.5 rounded-lg border border-[var(--color-edify-border)] bg-[var(--surface-1)] text-[13px] font-semibold">
              {CONTEXTS.map((c) => <option key={c.value} value={c.value}>{c.label}</option>)}
            </select>
          </label>
        </div>
        <label className="block">
          <span className="block text-[10.5px] font-bold uppercase tracking-wide muted mb-1">Subject</span>
          <input value={subject} onChange={(e) => setSubject(e.target.value)} placeholder="Optional" className="w-full h-10 px-2.5 rounded-lg border border-[var(--color-edify-border)] bg-[var(--surface-1)] text-[13px]" />
        </label>
        <label className="block">
          <span className="block text-[10.5px] font-bold uppercase tracking-wide muted mb-1">Message</span>
          <textarea value={body} onChange={(e) => setBody(e.target.value)} rows={5} placeholder="Write your message…" className="w-full px-2.5 py-2 rounded-lg border border-[var(--color-edify-border)] bg-[var(--surface-1)] text-[13px] resize-y" />
        </label>
        {err && <p className="text-[12px] text-rose-600 font-semibold">{err}</p>}
        <div className="flex items-center justify-end gap-2">
          <button onClick={() => router.push(backHref)} className="h-10 px-4 rounded-lg border border-[var(--color-edify-border)] text-[12.5px] font-bold hover:bg-[var(--surface-3)]">Cancel</button>
          <button disabled={!canSend} onClick={send} className="h-10 px-5 inline-flex items-center gap-1.5 rounded-lg bg-[var(--color-edify-primary)] hover:bg-[var(--color-edify-dark)] text-white text-[12.5px] font-bold disabled:opacity-50">
            {sent ? <><CheckCircle2 size={15} /> Sent</> : busy ? <><Loader2 size={15} className="animate-spin" /> Sending</> : <><Send size={15} /> Send message</>}
          </button>
        </div>
      </div>
    </div>
  );
}
