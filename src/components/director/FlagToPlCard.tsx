"use client";

import { useEffect, useState } from "react";
import { Flag, Send } from "lucide-react";

// The CD's "Flag an issue to a Program Lead" surface — the sanctioned CD action
// (the CD monitors + flags; the PL plans). Creates a persisted, PL-assigned,
// notified action item via /api/flags. No field-planning action by the CD.
const CATEGORIES: [string, string][] = [
  ["ssa", "Weak SSA movement"],
  ["target", "District behind target"],
  ["partner", "Partner underperformance"],
  ["staff", "Staff performance risk"],
  ["cluster", "Cluster gap"],
  ["fund", "Fund execution delay"],
  ["evidence", "Evidence backlog"],
  ["data_quality", "Data quality risk"],
  ["core_package", "Core package delay"],
];

export function FlagToPlCard() {
  const [pls, setPls] = useState<{ id: string; name: string }[]>([]);
  const [assignedToUserId, setAssignedToUserId] = useState("");
  const [category, setCategory] = useState("ssa");
  const [priority, setPriority] = useState("normal");
  const [scopeName, setScopeName] = useState("");
  const [note, setNote] = useState("");
  const [recommendedAction, setRecommendedAction] = useState("");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);

  useEffect(() => {
    fetch("/api/flags/program-leads", { credentials: "include" })
      .then((r) => r.json())
      .then((d) => {
        if (Array.isArray(d.programLeads)) {
          setPls(d.programLeads);
          if (d.programLeads[0]) setAssignedToUserId(d.programLeads[0].id);
        }
      })
      .catch(() => {});
  }, []);

  async function submit() {
    if (!assignedToUserId || !note.trim()) {
      setMsg({ ok: false, text: "Pick a Program Lead and describe the issue." });
      return;
    }
    setBusy(true);
    setMsg(null);
    try {
      const res = await fetch("/api/flags", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify({ assignedToUserId, category, priority, scopeName: scopeName || undefined, note, recommendedAction: recommendedAction || undefined }),
      }).then((r) => r.json());
      if (res.live) {
        setMsg({ ok: true, text: "Flag sent to the Program Lead — it's now in their Team Plan queue." });
        setNote("");
        setScopeName("");
        setRecommendedAction("");
      } else {
        setMsg({ ok: false, text: res.error ?? "Could not send the flag." });
      }
    } finally {
      setBusy(false);
    }
  }

  const input = "w-full rounded-lg border border-slate-200 bg-transparent px-2.5 py-1.5 text-sm text-[var(--text-primary)] dark:border-slate-700";

  return (
    <div className="rounded-2xl border border-slate-200 bg-white p-4 dark:border-slate-800 dark:bg-slate-900/40">
      <div className="flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wide muted">
        <Flag className="h-3.5 w-3.5" /> Flag an issue to a Program Lead
      </div>
      <p className="mt-1 text-xs muted">You monitor and flag; the PL plans. This creates a tracked, PL-assigned action item — not a field-planning action.</p>

      <div className="mt-3 grid grid-cols-2 gap-2">
        <label className="text-[11px] muted">
          Program Lead
          <select value={assignedToUserId} onChange={(e) => setAssignedToUserId(e.target.value)} className={input}>
            {pls.length === 0 && <option value="">No PLs found</option>}
            {pls.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
          </select>
        </label>
        <label className="text-[11px] muted">
          Issue
          <select value={category} onChange={(e) => setCategory(e.target.value)} className={input}>
            {CATEGORIES.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
          </select>
        </label>
        <label className="text-[11px] muted">
          Scope (region / district / school…)
          <input value={scopeName} onChange={(e) => setScopeName(e.target.value)} placeholder="e.g. Lira District" className={input} />
        </label>
        <label className="text-[11px] muted">
          Priority
          <select value={priority} onChange={(e) => setPriority(e.target.value)} className={input}>
            <option value="low">Low</option>
            <option value="normal">Normal</option>
            <option value="high">High</option>
            <option value="urgent">Urgent</option>
          </select>
        </label>
      </div>
      <textarea value={note} onChange={(e) => setNote(e.target.value)} rows={2} placeholder="Describe the issue the PL should act on…" className={`${input} mt-2`} />
      <input value={recommendedAction} onChange={(e) => setRecommendedAction(e.target.value)} placeholder="Recommended follow-up (optional)" className={`${input} mt-2`} />

      <div className="mt-3 flex items-center justify-between gap-2">
        {msg ? (
          <span className={`text-[11px] ${msg.ok ? "text-emerald-600" : "text-rose-500"}`}>{msg.text}</span>
        ) : <span />}
        <button onClick={submit} disabled={busy} className="inline-flex items-center gap-1.5 rounded-lg bg-slate-900 px-3 py-1.5 text-xs font-semibold text-white disabled:opacity-50 dark:bg-slate-100 dark:text-slate-900">
          <Send className="h-3.5 w-3.5" /> Send to PL
        </button>
      </div>
    </div>
  );
}
