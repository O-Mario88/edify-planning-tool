"use client";

// CCEO surface: partner debriefs awaiting review + merge (spec §8/§10).
// The CCEO reads the partner's field input, adds a review note, and merges it
// into their daily debrief — which then routes up to PL/CD/IA/HR. The partner
// record is preserved (linked, never overwritten).

import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { Handshake, ChevronDown, GitMerge, Loader2, CheckCircle2, AlertTriangle } from "lucide-react";
import { cn } from "@/lib/utils";
import type { BeDebrief } from "@/lib/api/surfaces";

function blockerLabel(k: string): string {
  return k.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

export function PartnerDebriefReviewCard() {
  const router = useRouter();
  const [rows, setRows] = useState<BeDebrief[]>([]);
  const [off, setOff] = useState(false);
  const [loading, setLoading] = useState(true);
  const [openId, setOpenId] = useState<string | null>(null);
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [merged, setMerged] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const res = await fetch("/api/debriefs", { credentials: "include" });
      const j = await res.json();
      if (j.live) { setRows(j.partnerInputs ?? []); setOff(false); } else { setOff(true); }
    } catch { setOff(true); }
    setLoading(false);
  }, []);
  useEffect(() => { void load(); }, [load]);

  const merge = useCallback(async (id: string) => {
    setBusy(id); setError(null);
    try {
      const res = await fetch("/api/debriefs/merge", {
        method: "POST", credentials: "include", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ partnerDebriefId: id, note }),
      });
      const j = await res.json();
      if (j.live && j.merged) {
        setMerged(`Merged and routed to PL, CD, IA, and HR (${j.routedTo} recipients).`);
        setRows((prev) => prev.filter((r) => r.id !== id));
        setOpenId(null); setNote("");
        router.refresh();
        setTimeout(() => setMerged(null), 3500);
      } else {
        setError(j.error || "Merge failed.");
      }
    } catch { setError("Could not reach the server."); }
    setBusy(null);
  }, [note, router]);

  if (off || (!loading && rows.length === 0 && !merged)) return null;

  return (
    <section className="card p-3.5">
      <header className="flex items-center justify-between gap-2 mb-2.5 flex-wrap">
        <h2 className="text-[13px] font-extrabold tracking-tight inline-flex items-center gap-1.5">
          <Handshake size={14} /> Partner debriefs awaiting review
          {rows.length > 0 && <span className="inline-grid place-items-center min-w-5 h-5 px-1.5 rounded-full bg-amber-100 text-amber-800 text-[10px] font-bold">{rows.length}</span>}
        </h2>
        <span className="inline-flex items-center gap-1 rounded-full bg-emerald-50 text-emerald-700 px-2 py-0.5 text-[10px] font-bold border border-emerald-200">Live · review &amp; merge</span>
      </header>

      {merged && (
        <p className="mb-2 text-[11.5px] font-semibold text-emerald-700 bg-emerald-50 border border-emerald-200 rounded-lg px-2.5 py-1.5 inline-flex items-center gap-1.5"><CheckCircle2 size={14} /> {merged}</p>
      )}
      {error && (
        <p className="mb-2 text-[11.5px] font-semibold text-rose-600 bg-rose-50 border border-rose-200 rounded-lg px-2.5 py-1.5 inline-flex items-center gap-1.5"><AlertTriangle size={14} /> {error}</p>
      )}

      {loading ? (
        <div className="py-6 text-center text-[12px] muted">Loading…</div>
      ) : (
        <div className="space-y-2">
          {rows.map((r) => {
            const isOpen = openId === r.id;
            return (
              <div key={r.id} className="rounded-xl border border-[var(--color-edify-border)] overflow-hidden">
                <button onClick={() => { setOpenId(isOpen ? null : r.id); setNote(""); }} className="w-full flex items-center gap-2 px-3 py-2.5 text-left hover:bg-slate-50">
                  <span className="h-8 w-8 rounded-lg bg-violet-50 text-violet-600 grid place-items-center shrink-0"><Handshake size={14} /></span>
                  <div className="flex-1 min-w-0">
                    <div className="text-[12px] font-bold truncate">{r.whatHappened || "Partner field input"}</div>
                    <div className="text-[10.5px] muted">Partner debrief · {new Date(r.submittedAt).toLocaleDateString()}{r.blockers.length ? ` · ${r.blockers.length} blocker${r.blockers.length > 1 ? "s" : ""}` : ""}</div>
                  </div>
                  <ChevronDown size={15} className={cn("muted transition-transform shrink-0", isOpen && "rotate-180")} />
                </button>
                {isOpen && (
                  <div className="px-3 pb-3 pt-1 border-t border-[var(--color-edify-divider)] space-y-2.5">
                    {r.whatHappened && <Detail label="What happened" value={r.whatHappened} />}
                    {r.whatDidNotGoWell && <Detail label="Challenges" value={r.whatDidNotGoWell} />}
                    {r.supportNeeded && <Detail label="Support needed" value={r.supportNeeded} />}
                    {r.blockers.length > 0 && (
                      <div>
                        <div className="text-[9.5px] font-bold uppercase tracking-wide muted mb-1">Blockers</div>
                        <div className="flex flex-wrap gap-1">
                          {r.blockers.map((b) => <span key={b} className="text-[10px] font-semibold rounded-md bg-rose-50 text-rose-700 border border-rose-200 px-1.5 py-0.5">{blockerLabel(b)}</span>)}
                        </div>
                      </div>
                    )}
                    <div>
                      <div className="text-[9.5px] font-bold uppercase tracking-wide muted mb-1">Your review note (optional)</div>
                      <textarea value={note} onChange={(e) => setNote(e.target.value)} rows={2} placeholder="Add context before merging into your daily debrief…" className="w-full rounded-lg border border-[var(--color-edify-border)] bg-white px-2.5 py-2 text-[12px] resize-none focus:outline-none focus:ring-2 focus:ring-emerald-200" />
                    </div>
                    <button onClick={() => void merge(r.id)} disabled={busy === r.id} className="w-full h-10 rounded-xl bg-emerald-600 hover:bg-emerald-500 disabled:opacity-60 text-white text-[12.5px] font-extrabold inline-flex items-center justify-center gap-2">
                      {busy === r.id ? <><Loader2 size={14} className="animate-spin" /> Merging…</> : <><GitMerge size={14} /> Merge into today’s debrief → route up</>}
                    </button>
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}
      <p className="mt-2 text-[10.5px] muted">Merging attaches the partner’s field input to your daily debrief and routes the combined record to PL, CD, IA, and HR. The partner record is preserved.</p>
    </section>
  );
}

function Detail({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div className="text-[9.5px] font-bold uppercase tracking-wide muted">{label}</div>
      <p className="text-[12px] text-slate-700 leading-snug">{value}</p>
    </div>
  );
}
