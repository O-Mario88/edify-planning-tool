"use client";

import { useEffect, useState } from "react";
import { CalendarPlus, Check, X, Loader2, CalendarRange } from "lucide-react";
import { csrfHeaders } from "@/lib/csrf-client";

// LeaveLive — the real, backend-backed leave workflow alongside the planning
// dashboard's visuals. A staffer requests leave; HR/CD approve or reject. Every
// row persists to Postgres (Leave model). Renders nothing when the backend is off.

type LeaveRow = {
  id: string; staffName: string; type: string; startDate: string; endDate: string;
  days: number; status: string; reason: string | null; createdAt: string;
};

const STATUS_TONE: Record<string, string> = {
  pending: "bg-amber-100 text-amber-700",
  approved: "bg-emerald-100 text-emerald-700",
  rejected: "bg-rose-100 text-rose-700",
};

const TYPES = ["annual", "sick", "compassionate", "unpaid"];

function daysBetween(a: string, b: string): number {
  const d1 = new Date(a).getTime(), d2 = new Date(b).getTime();
  if (Number.isNaN(d1) || Number.isNaN(d2) || d2 < d1) return 1;
  return Math.round((d2 - d1) / 86_400_000) + 1;
}

export function LeaveLive() {
  const [rows, setRows] = useState<LeaveRow[]>([]);
  const [canReview, setCanReview] = useState(false);
  const [live, setLive] = useState<boolean | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [form, setForm] = useState({ type: "annual", startDate: "", endDate: "", reason: "" });

  async function load() {
    const d = await fetch("/api/hr/leave").then((r) => r.json()).catch(() => null);
    if (!d) { setLive(false); return; }
    setLive(!!d.live);
    setCanReview(!!d.canReview);
    if (d.live) setRows(d.leave ?? []);
  }
  useEffect(() => { void load(); }, []);

  async function submit() {
    if (!form.startDate || !form.endDate) return;
    setBusy("submit");
    try {
      const res = await fetch("/api/hr/leave", {
        method: "POST",
        headers: { "Content-Type": "application/json", ...csrfHeaders() },
        body: JSON.stringify({ ...form, days: daysBetween(form.startDate, form.endDate) }),
      });
      const d = await res.json();
      if (d.live) { setForm({ type: "annual", startDate: "", endDate: "", reason: "" }); await load(); }
    } finally { setBusy(null); }
  }

  async function review(id: string, action: "approve" | "reject") {
    setBusy(id);
    try {
      const res = await fetch(`/api/hr/leave/${id}`, {
        method: "POST",
        headers: { "Content-Type": "application/json", ...csrfHeaders() },
        body: JSON.stringify({ action }),
      });
      const d = await res.json();
      if (d.live) await load();
    } finally { setBusy(null); }
  }

  if (live === false) return null;

  const pending = rows.filter((r) => r.status === "pending").length;

  return (
    <section className="card p-3.5">
      <header className="flex items-center justify-between gap-2 mb-3 flex-wrap">
        <div>
          <h2 className="text-body-lg font-extrabold tracking-tight inline-flex items-center gap-1.5">
            <CalendarRange size={15} className="text-[var(--color-edify-primary)]" /> Leave requests
          </h2>
          <p className="text-[11.5px] muted">{rows.length} request{rows.length === 1 ? "" : "s"} · {pending} pending review</p>
        </div>
        <span className="inline-flex items-center gap-1 rounded-full bg-[var(--color-edify-soft)] text-[var(--color-edify-primary)] px-2 py-0.5 text-[10px] font-bold border border-[var(--color-edify-border)]">Live · backend</span>
      </header>

      {/* Request form */}
      <div className="rounded-xl border border-[var(--color-edify-divider)] p-3 mb-3 grid grid-cols-12 gap-2 items-end">
        <label className="col-span-6 sm:col-span-3 text-[11px] font-semibold muted">
          Type
          <select value={form.type} onChange={(e) => setForm((f) => ({ ...f, type: e.target.value }))}
            className="mt-1 w-full h-9 px-2 rounded-lg border border-[var(--color-edify-border)] bg-transparent text-[12px] font-semibold capitalize">
            {TYPES.map((t) => <option key={t} value={t}>{t}</option>)}
          </select>
        </label>
        <label className="col-span-6 sm:col-span-3 text-[11px] font-semibold muted">
          Start
          <input type="date" value={form.startDate} onChange={(e) => setForm((f) => ({ ...f, startDate: e.target.value }))}
            className="mt-1 w-full h-9 px-2 rounded-lg border border-[var(--color-edify-border)] bg-transparent text-[12px]" />
        </label>
        <label className="col-span-6 sm:col-span-3 text-[11px] font-semibold muted">
          End
          <input type="date" value={form.endDate} onChange={(e) => setForm((f) => ({ ...f, endDate: e.target.value }))}
            className="mt-1 w-full h-9 px-2 rounded-lg border border-[var(--color-edify-border)] bg-transparent text-[12px]" />
        </label>
        <button type="button" onClick={submit} disabled={busy === "submit" || !form.startDate || !form.endDate}
          className="col-span-6 sm:col-span-3 h-9 px-3 rounded-xl bg-[var(--color-edify-primary)] text-white text-[12px] font-bold inline-flex items-center justify-center gap-1.5 disabled:opacity-50">
          {busy === "submit" ? <Loader2 size={13} className="animate-spin" /> : <CalendarPlus size={13} />} Request leave
        </button>
      </div>

      {/* List */}
      {rows.length === 0 ? (
        <p className="text-[12px] muted py-3 text-center">No leave requests yet.</p>
      ) : (
        <ul className="divide-y divide-[var(--color-edify-divider)]">
          {rows.map((r) => (
            <li key={r.id} className="py-2.5 flex items-center gap-3">
              <div className="flex-1 min-w-0">
                <div className="text-body font-extrabold tracking-tight truncate">
                  {r.staffName} <span className="font-semibold muted capitalize">· {r.type}</span>
                </div>
                <div className="text-caption muted truncate">
                  {r.startDate} → {r.endDate} · {r.days} day{r.days === 1 ? "" : "s"}{r.reason ? ` · ${r.reason}` : ""}
                </div>
              </div>
              <span className={`inline-flex items-center px-1.5 py-[2px] rounded-md text-[10px] font-extrabold whitespace-nowrap capitalize ${STATUS_TONE[r.status] ?? "bg-[var(--color-edify-soft)]"}`}>
                {r.status}
              </span>
              {canReview && r.status === "pending" && (
                <div className="flex items-center gap-1 shrink-0">
                  <button type="button" onClick={() => review(r.id, "approve")} disabled={busy === r.id}
                    className="h-7 w-7 rounded-md border border-emerald-200 text-emerald-700 inline-flex items-center justify-center hover:bg-emerald-50 disabled:opacity-50" aria-label="Approve">
                    {busy === r.id ? <Loader2 size={12} className="animate-spin" /> : <Check size={13} />}
                  </button>
                  <button type="button" onClick={() => review(r.id, "reject")} disabled={busy === r.id}
                    className="h-7 w-7 rounded-md border border-rose-200 text-rose-700 inline-flex items-center justify-center hover:bg-rose-50 disabled:opacity-50" aria-label="Reject">
                    <X size={13} />
                  </button>
                </div>
              )}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
