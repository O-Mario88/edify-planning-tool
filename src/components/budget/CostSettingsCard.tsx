"use client";

// The CD-owned Country Cost Register. Only the Country Director can edit — every
// scheduled activity is auto-costed from these numbers, so this is the single
// lever that controls every budget and fund request. Backend enforces the
// CD-only write (COST_SETTINGS_MANAGE), versions each change, and keeps an
// immutable, audited history (old→new, who, when, why).

import { useEffect, useState } from "react";
import { SlidersHorizontal, Check, Pencil, X, Plus, History, Loader2 } from "lucide-react";
import { EmptyState, ErrorState, LoadingState } from "@/components/ui/DataStates";
import { csrfHeaders } from "@/lib/csrf-client";
import type { BeCostSetting, BeCostHistoryRow } from "@/lib/api/surfaces";

const ugx = (n: number) => `UGX ${n.toLocaleString()}`;

export function CostSettingsCard() {
  const [rows, setRows] = useState<BeCostSetting[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [editKey, setEditKey] = useState<string | null>(null);
  const [draft, setDraft] = useState("");
  const [reason, setReason] = useState("");
  const [saving, setSaving] = useState(false);
  const [formErr, setFormErr] = useState<string | null>(null);
  // Create form
  const [showCreate, setShowCreate] = useState(false);
  const [nk, setNk] = useState({ key: "", label: "", unitCost: "", fy: "" });
  // History
  const [historyKey, setHistoryKey] = useState<string | null>(null);
  const [history, setHistory] = useState<BeCostHistoryRow[] | null>(null);

  const load = () => {
    setLoading(true); setError(null);
    fetch("/api/budget/cost-settings", { credentials: "include" })
      .then((r) => r.json())
      .then((j) => { if (j.live) setRows(j.settings as BeCostSetting[]); else setError(j.error || "Could not load cost settings"); })
      .catch(() => setError("Could not reach the server"))
      .finally(() => setLoading(false));
  };
  useEffect(load, []);

  const startEdit = (s: BeCostSetting) => { setEditKey(s.key); setDraft(String(s.unitCost)); setReason(""); setFormErr(null); };
  const cancel = () => { setEditKey(null); setDraft(""); setReason(""); setFormErr(null); };

  async function post(body: Record<string, unknown>): Promise<boolean> {
    setSaving(true); setFormErr(null);
    try {
      const j = await fetch("/api/budget/cost-settings", {
        method: "POST", credentials: "include", headers: { "Content-Type": "application/json", ...csrfHeaders() }, body: JSON.stringify(body),
      }).then((r) => r.json());
      if (j.live) { load(); return true; }
      setFormErr(j.error || "The change was rejected.");
      return false;
    } catch { setFormErr("Could not reach the server."); return false; }
    finally { setSaving(false); }
  }

  const save = async (s: BeCostSetting) => {
    const unitCost = Number(draft);
    if (!Number.isFinite(unitCost) || unitCost < 0) { setFormErr("Enter a valid non-negative amount."); return; }
    if (await post({ key: s.key, label: s.label, unitCost, fy: s.fy ?? undefined, reason: reason.trim() || undefined })) cancel();
  };

  const create = async () => {
    const unitCost = Number(nk.unitCost);
    if (!nk.key.trim() || !nk.label.trim()) { setFormErr("Key and label are required."); return; }
    if (!Number.isFinite(unitCost) || unitCost < 0) { setFormErr("Enter a valid non-negative amount."); return; }
    if (await post({ key: nk.key.trim(), label: nk.label.trim(), unitCost, fy: nk.fy.trim() || undefined, reason: reason.trim() || "New rate" })) {
      setShowCreate(false); setNk({ key: "", label: "", unitCost: "", fy: "" }); setReason("");
    }
  };

  const toggleHistory = async (key: string) => {
    if (historyKey === key) { setHistoryKey(null); setHistory(null); return; }
    setHistoryKey(key); setHistory(null);
    const j = await fetch(`/api/budget/cost-settings/history?key=${encodeURIComponent(key)}`, { credentials: "include" }).then((r) => r.json());
    setHistory(j.live && Array.isArray(j.history) ? j.history : []);
  };

  const inp = "px-1.5 py-0.5 rounded border border-[var(--color-edify-border)] text-[11px]";

  return (
    <section className="card p-3.5">
      <header className="flex items-center justify-between gap-2 mb-2.5 flex-wrap">
        <h2 className="text-[13px] font-extrabold tracking-tight inline-flex items-center gap-1.5"><SlidersHorizontal size={14} /> Country Cost Register · CD rate card</h2>
        <div className="flex items-center gap-2">
          <button onClick={() => { setShowCreate((v) => !v); setFormErr(null); }} className="inline-flex items-center gap-1 h-7 px-2.5 rounded-lg bg-[var(--color-edify-primary)] hover:bg-[var(--color-edify-dark)] text-white text-[10.5px] font-bold"><Plus size={12} /> Add rate</button>
          <span className="inline-flex items-center gap-1 rounded-full bg-amber-50 text-amber-700 px-2 py-0.5 text-[10px] font-bold border border-amber-200">CD-controlled · versioned</span>
        </div>
      </header>

      {showCreate && (
        <div className="mb-2.5 rounded-lg border border-[var(--color-edify-border)] p-2.5 space-y-1.5">
          <div className="grid grid-cols-2 gap-1.5">
            <input placeholder="key (e.g. lunch)" value={nk.key} onChange={(e) => setNk({ ...nk, key: e.target.value })} className={`${inp} w-full font-mono`} />
            <input placeholder="Label" value={nk.label} onChange={(e) => setNk({ ...nk, label: e.target.value })} className={`${inp} w-full`} />
            <input placeholder="Unit cost (UGX)" type="number" value={nk.unitCost} onChange={(e) => setNk({ ...nk, unitCost: e.target.value })} className={`${inp} w-full text-right tabular`} />
            <input placeholder="FY (optional)" value={nk.fy} onChange={(e) => setNk({ ...nk, fy: e.target.value })} className={`${inp} w-full`} />
          </div>
          <input placeholder="Reason for this rate" value={reason} onChange={(e) => setReason(e.target.value)} className={`${inp} w-full`} />
          <div className="flex items-center justify-end gap-1.5">
            <button onClick={() => { setShowCreate(false); setFormErr(null); }} className="px-2 py-1 rounded border border-[var(--color-edify-border)] text-[11px]">Cancel</button>
            <button disabled={saving} onClick={create} className="inline-flex items-center gap-1 px-2.5 py-1 rounded bg-emerald-500 text-white text-[11px] font-bold disabled:opacity-50">{saving ? <Loader2 size={12} className="animate-spin" /> : <Check size={12} />} Add</button>
          </div>
        </div>
      )}
      {formErr && <p className="mb-2 text-[11px] text-rose-600 font-semibold">{formErr}</p>}

      {loading ? (
        <LoadingState compact />
      ) : error ? (
        <ErrorState compact message={error} onRetry={load} />
      ) : !rows || rows.length === 0 ? (
        <EmptyState compact title="No cost settings yet" message="Use “Add rate” to register an official cost — every scheduled activity then costs itself automatically." />
      ) : (
        <>
          <p className="text-[11px] muted mb-2.5 leading-snug">These are the only costs the system uses. Change a rate and every budget and fund request updates instantly; past budgets keep their snapshotted cost.</p>
          <ul className="divide-y divide-[var(--color-edify-divider)]">
            {rows.map((s) => (
              <li key={s.key} className="py-1.5 text-[11.5px]">
                <div className="flex items-center justify-between gap-2">
                  <span className="min-w-0 truncate">
                    <span className="font-semibold">{s.label}</span>
                    {typeof s.version === "number" && s.version > 1 && <span className="ml-1.5 text-[8.5px] font-bold text-violet-600">v{s.version}</span>}
                    <span className="block text-[9px] muted font-mono truncate">{s.key}</span>
                  </span>
                  {editKey === s.key ? (
                    <span className="inline-flex items-center gap-1 shrink-0">
                      <input autoFocus type="number" value={draft} onChange={(e) => setDraft(e.target.value)} className={`${inp} w-24 text-right tabular`} />
                      <input placeholder="reason" value={reason} onChange={(e) => setReason(e.target.value)} className={`${inp} w-24`} />
                      <button disabled={saving} onClick={() => save(s)} className="p-1 rounded bg-emerald-500 text-white hover:bg-emerald-600 disabled:opacity-50"><Check size={12} /></button>
                      <button onClick={cancel} className="p-1 rounded border border-[var(--color-edify-border)] hover:bg-[var(--surface-3)]"><X size={12} /></button>
                    </span>
                  ) : (
                    <span className="inline-flex items-center gap-1.5 shrink-0">
                      <span className="font-bold tabular">{ugx(s.unitCost)}</span>
                      <button onClick={() => toggleHistory(s.key)} className="p-1 rounded text-slate-400 hover:text-[var(--color-edify-text)] hover:bg-[var(--surface-3)]" title="Change history"><History size={11} /></button>
                      <button onClick={() => startEdit(s)} className="p-1 rounded text-slate-400 hover:text-[var(--color-edify-text)] hover:bg-[var(--surface-3)]" title="Edit rate"><Pencil size={11} /></button>
                    </span>
                  )}
                </div>
                {historyKey === s.key && (
                  <div className="mt-1.5 ml-1 border-l-2 border-violet-200 pl-2 space-y-0.5">
                    {history === null ? <span className="text-[10px] muted">Loading…</span>
                      : history.length === 0 ? <span className="text-[10px] muted">No recorded changes.</span>
                      : history.map((h) => (
                        <div key={h.id} className="text-[10px] muted">
                          v{h.version}: {h.oldUnitCost != null ? `${ugx(h.oldUnitCost)} → ` : ""}<span className="font-semibold text-[var(--color-edify-text)]">{ugx(h.newUnitCost)}</span>
                          {h.reason ? ` · ${h.reason}` : ""} · {new Date(h.changedAt).toLocaleDateString()}
                        </div>
                      ))}
                  </div>
                )}
              </li>
            ))}
          </ul>
        </>
      )}
    </section>
  );
}
