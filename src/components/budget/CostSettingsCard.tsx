"use client";

// The CD-owned rate card. Only the Country Director can edit — every scheduled
// activity is auto-costed from these numbers, so this is the single lever that
// controls every budget and fund request in the country. Backend enforces the
// CD-only write (COST_SETTINGS_MANAGE); this card just edits in place.

import { useEffect, useState } from "react";
import { SlidersHorizontal, Check, Pencil, X } from "lucide-react";
import { EmptyState, ErrorState, LoadingState } from "@/components/ui/DataStates";
import type { BeCostSetting } from "@/lib/api/surfaces";

const ugx = (n: number) => `UGX ${n.toLocaleString()}`;

export function CostSettingsCard() {
  const [rows, setRows] = useState<BeCostSetting[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [editKey, setEditKey] = useState<string | null>(null);
  const [draft, setDraft] = useState("");
  const [saving, setSaving] = useState(false);

  const load = () => {
    setLoading(true); setError(null);
    fetch("/api/budget/cost-settings", { credentials: "include" })
      .then((r) => r.json())
      .then((j) => { if (j.live) setRows(j.settings as BeCostSetting[]); else setError(j.error || "Could not load cost settings"); })
      .catch(() => setError("Could not reach the server"))
      .finally(() => setLoading(false));
  };
  useEffect(load, []);

  const startEdit = (s: BeCostSetting) => { setEditKey(s.key); setDraft(String(s.unitCost)); };
  const cancel = () => { setEditKey(null); setDraft(""); };

  const save = async (s: BeCostSetting) => {
    const unitCost = Number(draft);
    if (!Number.isFinite(unitCost) || unitCost < 0) return;
    setSaving(true);
    try {
      const res = await fetch("/api/budget/cost-settings", {
        method: "POST", credentials: "include", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ key: s.key, label: s.label, unitCost, fy: s.fy ?? undefined }),
      });
      const j = await res.json();
      if (j.live) {
        setRows((prev) => prev?.map((r) => (r.key === s.key ? { ...r, unitCost } : r)) ?? null);
        cancel();
      } else { setError(j.error || "Save was rejected"); }
    } catch { setError("Could not save"); }
    setSaving(false);
  };

  return (
    <section className="card p-3.5">
      <header className="flex items-center justify-between gap-2 mb-2.5 flex-wrap">
        <h2 className="text-[13px] font-extrabold tracking-tight inline-flex items-center gap-1.5"><SlidersHorizontal size={14} /> Cost settings · CD rate card</h2>
        <span className="inline-flex items-center gap-1 rounded-full bg-amber-50 text-amber-700 px-2 py-0.5 text-[10px] font-bold border border-amber-200">CD-controlled</span>
      </header>

      {loading ? (
        <LoadingState compact />
      ) : error ? (
        <ErrorState compact message={error} onRetry={load} />
      ) : !rows || rows.length === 0 ? (
        <EmptyState compact title="No cost settings yet" message="Add official rates and every scheduled activity will cost itself automatically." />
      ) : (
        <>
          <p className="text-[11px] muted mb-2.5 leading-snug">These are the only costs the system uses. Change a rate and every budget and fund request updates instantly.</p>
          <ul className="divide-y divide-[var(--color-edify-divider)]">
            {rows.map((s) => (
              <li key={s.key} className="flex items-center justify-between gap-2 py-1.5 text-[11.5px]">
                <span className="min-w-0 truncate"><span className="font-semibold">{s.label}</span><span className="block text-[9px] muted font-mono truncate">{s.key}</span></span>
                {editKey === s.key ? (
                  <span className="inline-flex items-center gap-1 shrink-0">
                    <input autoFocus type="number" value={draft} onChange={(e) => setDraft(e.target.value)} className="w-24 px-1.5 py-0.5 rounded border border-[var(--color-edify-border)] text-[11px] tabular text-right" />
                    <button disabled={saving} onClick={() => save(s)} className="p-1 rounded bg-emerald-500 text-white hover:bg-emerald-600 disabled:opacity-50"><Check size={12} /></button>
                    <button onClick={cancel} className="p-1 rounded border border-[var(--color-edify-border)] hover:bg-[var(--surface-3)]"><X size={12} /></button>
                  </span>
                ) : (
                  <span className="inline-flex items-center gap-1.5 shrink-0">
                    <span className="font-bold tabular">{ugx(s.unitCost)}</span>
                    <button onClick={() => startEdit(s)} className="p-1 rounded text-slate-400 hover:text-[var(--color-edify-text)] hover:bg-[var(--surface-3)]" title="Edit rate"><Pencil size={11} /></button>
                  </span>
                )}
              </li>
            ))}
          </ul>
        </>
      )}
    </section>
  );
}
