"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { Upload, Loader2, FileText, Image as ImageIcon, Download, Eye, Check, X, Paperclip } from "lucide-react";

// EvidencePanel — the REAL, backend-backed evidence surface for an activity.
// Upload a file (multipart → POST /api/evidence/upload → backend disk + DB),
// list what's attached, preview images/PDF inline + download anything, and
// (for reviewers) accept/return — which drives Activity.evidenceStatus, the
// gate the IA + accountant payment flow keys off.

type EvidenceItem = {
  id: string; kind: string; status: string; originalName: string | null;
  mimeType: string | null; uploadedBy: string; uploadedAt: string; reviewNote: string | null;
};

const KINDS: { value: string; label: string }[] = [
  { value: "visit_form", label: "Visit form" },
  { value: "attendance_form", label: "Attendance form" },
  { value: "meeting_minutes", label: "Meeting minutes" },
  { value: "resolutions", label: "Resolutions" },
  { value: "evaluation_form", label: "Evaluation form" },
  { value: "assessment_form", label: "Assessment / SSA form" },
  { value: "project_report", label: "Project report" },
  { value: "coaching_notes", label: "Coaching notes" },
  { value: "photo", label: "Photo" },
  { value: "pdf", label: "PDF document" },
  { value: "school_stamp", label: "School stamp" },
];

const STATUS_TONE: Record<string, string> = {
  uploaded: "bg-amber-100 text-amber-700",
  accepted: "bg-emerald-100 text-emerald-700",
  returned: "bg-rose-100 text-rose-700",
  rejected: "bg-rose-100 text-rose-700",
};

function isImage(m: string | null) { return !!m && m.startsWith("image/"); }
function isPdf(m: string | null) { return m === "application/pdf"; }

export function EvidencePanel({ activityId, canReview = false }: { activityId: string; canReview?: boolean }) {
  const [items, setItems] = useState<EvidenceItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [kind, setKind] = useState("visit_form");
  const [preview, setPreview] = useState<EvidenceItem | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const d = await fetch(`/api/evidence/activity/${activityId}`, { cache: "no-store" }).then((r) => r.json());
      setItems(d.evidence ?? []);
    } catch { setError("Could not load evidence."); }
    finally { setLoading(false); }
  }, [activityId]);

  useEffect(() => { void load(); }, [load]);

  async function onUpload(file: File) {
    setBusy(true); setError(null);
    try {
      const form = new FormData();
      form.append("file", file);
      form.append("activityId", activityId);
      form.append("kind", kind);
      const res = await fetch("/api/evidence/upload", { method: "POST", body: form });
      const d = await res.json();
      if (!res.ok) { setError(d.error ?? "Upload failed."); return; }
      if (fileRef.current) fileRef.current.value = "";
      await load();
    } catch { setError("Upload failed — check your connection."); }
    finally { setBusy(false); }
  }

  async function review(id: string, action: "accept" | "return") {
    let note: string | undefined;
    if (action === "return") {
      note = window.prompt("Reason for returning this evidence:") ?? undefined;
      if (!note) return;
    }
    setBusy(true);
    try {
      await fetch(`/api/evidence/${id}/review`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action, note }),
      });
      if (preview?.id === id) setPreview(null);
      await load();
    } finally { setBusy(false); }
  }

  return (
    <section className="card p-3.5">
      <header className="flex items-center justify-between gap-2 mb-3 flex-wrap">
        <h3 className="text-[13px] font-extrabold tracking-tight inline-flex items-center gap-1.5">
          <Paperclip size={14} className="text-[var(--color-edify-primary)]" /> Evidence
          <span className="text-[11px] font-semibold muted">({items.length})</span>
        </h3>
        <span className="inline-flex items-center gap-1 rounded-full bg-[var(--color-edify-soft)] text-[var(--color-edify-primary)] px-2 py-0.5 text-[10px] font-bold border border-[var(--color-edify-border)]">Live · backend</span>
      </header>

      {/* Upload row */}
      <div className="rounded-xl border border-[var(--color-edify-divider)] p-3 mb-3 flex flex-wrap items-end gap-2">
        <label className="text-[11px] font-semibold muted">
          Document type
          <select value={kind} onChange={(e) => setKind(e.target.value)}
            className="mt-1 block h-9 px-2 rounded-lg border border-[var(--color-edify-border)] bg-transparent text-[12px] font-semibold">
            {KINDS.map((k) => <option key={k.value} value={k.value}>{k.label}</option>)}
          </select>
        </label>
        <input
          ref={fileRef} type="file"
          accept="image/*,application/pdf,.doc,.docx,.xls,.xlsx,.csv"
          onChange={(e) => { const f = e.target.files?.[0]; if (f) void onUpload(f); }}
          className="hidden" id={`ev-file-${activityId}`}
        />
        <button type="button" disabled={busy} onClick={() => fileRef.current?.click()}
          className="h-9 px-3 rounded-xl bg-[var(--color-edify-primary)] text-white text-[12px] font-bold inline-flex items-center gap-1.5 disabled:opacity-50">
          {busy ? <Loader2 size={13} className="animate-spin" /> : <Upload size={13} />} Upload file
        </button>
        <span className="text-[10.5px] muted">PDF, image, Word, Excel or CSV · max 10MB</span>
      </div>

      {error && <p className="text-[11.5px] text-rose-600 font-semibold mb-2">{error}</p>}

      {/* List */}
      {loading ? (
        <p className="text-[12px] muted py-3 text-center inline-flex items-center gap-1.5 justify-center w-full"><Loader2 size={13} className="animate-spin" /> Loading…</p>
      ) : items.length === 0 ? (
        <p className="text-[12px] muted py-3 text-center">No evidence uploaded yet.</p>
      ) : (
        <ul className="divide-y divide-[var(--color-edify-divider)]">
          {items.map((it) => (
            <li key={it.id} className="py-2.5 flex items-center gap-3">
              <span className="h-9 w-9 rounded-md bg-[var(--color-edify-soft)]/80 text-[var(--color-edify-primary)] grid place-items-center shrink-0">
                {isImage(it.mimeType) ? <ImageIcon size={14} /> : <FileText size={14} />}
              </span>
              <div className="flex-1 min-w-0">
                <div className="text-body font-extrabold tracking-tight truncate">{it.originalName ?? it.kind}</div>
                <div className="text-caption muted truncate">{it.kind.replace(/_/g, " ")}{it.reviewNote ? ` · ${it.reviewNote}` : ""}</div>
              </div>
              <span className={`inline-flex items-center px-1.5 py-[2px] rounded-md text-[10px] font-extrabold capitalize ${STATUS_TONE[it.status] ?? "bg-[var(--color-edify-soft)]"}`}>{it.status}</span>
              <div className="flex items-center gap-1 shrink-0">
                <button type="button" onClick={() => setPreview(preview?.id === it.id ? null : it)} aria-label="Preview"
                  className="h-7 w-7 rounded-md border border-[var(--color-edify-border)] inline-flex items-center justify-center hover:bg-[var(--color-edify-soft)]/40"><Eye size={13} /></button>
                <a href={`/api/evidence/${it.id}/file?download=1`} aria-label="Download" download
                  className="h-7 w-7 rounded-md border border-[var(--color-edify-border)] inline-flex items-center justify-center hover:bg-[var(--color-edify-soft)]/40"><Download size={13} /></a>
                {canReview && it.status === "uploaded" && (
                  <>
                    <button type="button" disabled={busy} onClick={() => review(it.id, "accept")} aria-label="Accept"
                      className="h-7 w-7 rounded-md border border-emerald-200 text-emerald-700 inline-flex items-center justify-center hover:bg-emerald-50 disabled:opacity-50"><Check size={13} /></button>
                    <button type="button" disabled={busy} onClick={() => review(it.id, "return")} aria-label="Return"
                      className="h-7 w-7 rounded-md border border-rose-200 text-rose-700 inline-flex items-center justify-center hover:bg-rose-50 disabled:opacity-50"><X size={13} /></button>
                  </>
                )}
              </div>
            </li>
          ))}
        </ul>
      )}

      {/* Inline preview */}
      {preview && (
        <div className="mt-3 rounded-xl border border-[var(--color-edify-divider)] overflow-hidden">
          <div className="flex items-center justify-between px-3 py-2 bg-[var(--color-edify-soft)]/40">
            <span className="text-[12px] font-bold truncate">{preview.originalName ?? preview.kind}</span>
            <button type="button" onClick={() => setPreview(null)} className="text-[11px] font-semibold text-[var(--color-edify-primary)]">Close</button>
          </div>
          {isImage(preview.mimeType) ? (
            // eslint-disable-next-line @next/next/no-img-element
            <img src={`/api/evidence/${preview.id}/file`} alt={preview.originalName ?? "evidence"} className="max-h-[480px] w-full object-contain bg-black/5" />
          ) : isPdf(preview.mimeType) ? (
            <iframe src={`/api/evidence/${preview.id}/file`} title={preview.originalName ?? "evidence"} className="w-full h-[480px] bg-white" />
          ) : (
            <div className="p-6 text-center text-[12px] muted">
              This file type can&apos;t preview inline.{" "}
              <a href={`/api/evidence/${preview.id}/file?download=1`} download className="text-[var(--color-edify-primary)] font-semibold underline">Download to view</a>.
            </div>
          )}
        </div>
      )}
    </section>
  );
}
