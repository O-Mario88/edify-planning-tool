"use client";

// LiveCompose — a real, backend-wired message composer that enforces the
// role-specific message policy (spec §5/§6/§8):
//
//   Step 1  choose a recipient (role-scoped on the backend)
//   Step 2  choose a CONTEXT — the options change based on (yourRole → theirRole)
//   Step 3  attach a linked record when the context requires one
//   Step 4  write + send
//
// The composer never lets a message go without a context, and the context list
// is fetched live per-recipient from /api/messages/contexts so it can never
// drift from what the backend will accept. Send -> redirect to /messages.

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { Send, Loader2, CheckCircle2, Link2 } from "lucide-react";
import { EmptyState, ErrorState, LoadingState } from "@/components/ui/DataStates";
import { csrfHeaders } from "@/lib/csrf-client";

type Recipient = { id: string; name: string; role: string };
type ContextOption = { key: string; label: string; requiresLinkedRecord: boolean; recordTypes: string[] };

const roleLabel = (r: string) => r.replace(/([a-z])([A-Z])/g, "$1 $2");
const recordTypeLabel = (t: string) => t.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());

export function LiveCompose({ backHref = "/messages" }: { backHref?: string }) {
  const router = useRouter();
  const [recipients, setRecipients] = useState<Recipient[] | null>(null);
  const [loadErr, setLoadErr] = useState<string | null>(null);

  const [recipientId, setRecipientId] = useState("");
  const [contexts, setContexts] = useState<ContextOption[] | null>(null);
  const [contextsErr, setContextsErr] = useState<string | null>(null);
  const [contextKey, setContextKey] = useState("");
  const [recordType, setRecordType] = useState("");
  const [contextId, setContextId] = useState("");
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

  // Load the role-specific contexts whenever the recipient changes (spec §6).
  // State is only set inside the async resolution (never synchronously in the
  // effect body) so the composer never triggers cascading renders.
  useEffect(() => {
    let cancelled = false;
    if (!recipientId) return;
    fetch(`/api/messages/contexts?recipientId=${encodeURIComponent(recipientId)}`, { credentials: "include" })
      .then((r) => r.json())
      .then((j) => {
        if (cancelled) return;
        if (j.live) {
          const list = (j.contexts as ContextOption[]) ?? [];
          setContexts(list);
          const first = list[0];
          setContextKey(first?.key ?? "");
          setRecordType(first?.recordTypes?.[0] ?? "");
          setContextId("");
          setContextsErr(null);
        } else { setContexts([]); setContextsErr(j.error || "Could not load contexts"); }
      })
      .catch(() => { if (!cancelled) { setContexts([]); setContextsErr("Could not reach the server"); } });
    return () => { cancelled = true; };
  }, [recipientId]);

  const selectedContext = contexts?.find((c) => c.key === contextKey) ?? null;
  const needsRecord = !!selectedContext?.requiresLinkedRecord;
  const canSend =
    !!recipientId && !!contextKey && body.trim().length > 0 && !busy &&
    (!needsRecord || contextId.trim().length > 0);

  const onPickContext = (key: string) => {
    setContextKey(key);
    const ctx = contexts?.find((c) => c.key === key);
    setRecordType(ctx?.recordTypes?.[0] ?? "");
    setContextId("");
  };

  const send = async () => {
    setBusy(true); setErr(null);
    try {
      const res = await fetch("/api/messages", {
        method: "POST", credentials: "include", headers: { "Content-Type": "application/json", ...csrfHeaders() },
        body: JSON.stringify({
          recipientId,
          contextKey,
          contextType: recordType || undefined,
          contextId: contextId.trim() || undefined,
          subject: subject.trim() || undefined,
          body: body.trim(),
        }),
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

  const inputCls = "w-full h-10 px-2.5 rounded-lg border border-[var(--color-edify-border)] bg-[var(--surface-1)] text-[13px] font-semibold";
  const lblCls = "block text-[10.5px] font-bold uppercase tracking-wide muted mb-1";

  return (
    <div className="max-w-[720px] space-y-3.5">
      <div className="card p-4 space-y-3">
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
          <label className="block">
            <span className={lblCls}>To</span>
            <select value={recipientId} onChange={(e) => setRecipientId(e.target.value)} className={inputCls}>
              {recipients.map((r) => <option key={r.id} value={r.id}>{r.name} · {roleLabel(r.role)}</option>)}
            </select>
          </label>
          <label className="block">
            <span className={lblCls}>Context (required)</span>
            {contexts === null ? (
              <div className="h-10 inline-flex items-center gap-1.5 text-[12px] muted"><Loader2 size={14} className="animate-spin" /> Loading contexts…</div>
            ) : contexts.length === 0 ? (
              <div className="h-10 inline-flex items-center text-[12px] text-amber-600 font-semibold">No allowed topics for this recipient.</div>
            ) : (
              <select value={contextKey} onChange={(e) => onPickContext(e.target.value)} className={inputCls}>
                {contexts.map((c) => <option key={c.key} value={c.key}>{c.label}{c.requiresLinkedRecord ? " *" : ""}</option>)}
              </select>
            )}
          </label>
        </div>

        {needsRecord && (
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 rounded-lg border border-dashed border-[var(--color-edify-border)] p-3 bg-[var(--surface-2)]">
            {selectedContext!.recordTypes.length > 1 && (
              <label className="block">
                <span className={lblCls}>Record type</span>
                <select value={recordType} onChange={(e) => setRecordType(e.target.value)} className={inputCls}>
                  {selectedContext!.recordTypes.map((t) => <option key={t} value={t}>{recordTypeLabel(t)}</option>)}
                </select>
              </label>
            )}
            <label className="block">
              <span className={lblCls}><Link2 size={11} className="inline -mt-0.5 mr-1" />Linked record ID (required)</span>
              <input value={contextId} onChange={(e) => setContextId(e.target.value)} placeholder={`${recordTypeLabel(recordType || "record")} id`} className="w-full h-10 px-2.5 rounded-lg border border-[var(--color-edify-border)] bg-[var(--surface-1)] text-[13px]" />
            </label>
          </div>
        )}

        <label className="block">
          <span className={lblCls}>Subject</span>
          <input value={subject} onChange={(e) => setSubject(e.target.value)} placeholder="Optional" className="w-full h-10 px-2.5 rounded-lg border border-[var(--color-edify-border)] bg-[var(--surface-1)] text-[13px]" />
        </label>
        <label className="block">
          <span className={lblCls}>Message</span>
          <textarea value={body} onChange={(e) => setBody(e.target.value)} rows={5} placeholder="Write your message…" className="w-full px-2.5 py-2 rounded-lg border border-[var(--color-edify-border)] bg-[var(--surface-1)] text-[13px] resize-y" />
        </label>
        {(err || contextsErr) && <p className="text-[12px] text-rose-600 font-semibold">{err || contextsErr}</p>}
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
