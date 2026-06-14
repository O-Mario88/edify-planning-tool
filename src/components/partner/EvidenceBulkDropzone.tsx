"use client";

// EvidenceBulkDropzone — drag-drop / file-picker for partner evidence.
//
// AUDIT FIX: the previous version's onDrop was a no-op — files were
// silently discarded. This version wires every accepted file through
// the `partnerUploadEvidence` server action and surfaces per-file
// success/failure status inline.
//
// Routing rule: every uploaded file goes to the activity selected in
// the top control. If exactly one Delivered activity is available, it
// auto-selects; if multiple are available, the partner picks; if none
// are available, the dropzone explains why uploads are blocked.

import { useEffect, useRef, useState, useTransition } from "react";
import { useRouter } from "next/navigation";
import { Upload, FileText, CheckCircle2, Loader2, AlertCircle } from "lucide-react";
import { useDemoStore } from "@/components/demo/DemoStore";
import { csrfHeaders } from "@/lib/csrf-client";
import { cn } from "@/lib/utils";

// Each activity passed in is one the partner has marked Delivered and
// is awaiting evidence. Source: PartnerActivity rows in the store.
export type EligibleActivity = {
  id:        string;
  title:     string;
  schoolId:  string;
};

type UploadEntry = {
  id:        string;
  filename:  string;
  bytes:     number;
  status:    "pending" | "ok" | "error";
  message?:  string;
  uri?:      string;
};

const MAX_FILE_BYTES = 25 * 1024 * 1024;

// The backend's accepted evidence kinds (evidence.service VALID_KINDS).
const EVIDENCE_KINDS: { value: string; label: string }[] = [
  { value: "visit_form", label: "Visit form" },
  { value: "attendance_form", label: "Attendance form" },
  { value: "meeting_minutes", label: "Meeting minutes" },
  { value: "assessment_form", label: "Assessment form" },
  { value: "evaluation_form", label: "Evaluation form" },
  { value: "school_stamp", label: "School stamp" },
  { value: "photo", label: "Photo" },
  { value: "project_report", label: "Project report" },
];

export function EvidenceBulkDropzone({
  eligibleActivities,
}: {
  eligibleActivities: EligibleActivity[];
}) {
  const [over, setOver] = useState(false);
  const [activityId, setActivityId] = useState<string>(eligibleActivities[0]?.id ?? "");
  const [kind, setKind] = useState<string>(EVIDENCE_KINDS[0].value);
  const [uploads, setUploads] = useState<UploadEntry[]>([]);
  const [pending, startTransition] = useTransition();
  const fileInputRef = useRef<HTMLInputElement>(null);
  const { pushToast } = useDemoStore();
  const router = useRouter();

  // Keep the selected activity in sync if the parent's eligible list
  // changes (e.g. another tab marks one Delivered).
  useEffect(() => {
    if (!eligibleActivities.some((a) => a.id === activityId)) {
      setActivityId(eligibleActivities[0]?.id ?? "");
    }
  }, [eligibleActivities, activityId]);

  const hasActivity = activityId.length > 0;
  const single = eligibleActivities.length === 1;

  function acceptFiles(files: FileList | File[]) {
    if (!hasActivity) {
      pushToast({
        tone: "warning",
        title: "Pick a delivered activity first",
        body: "Evidence can only attach to an activity you've marked Delivered.",
      });
      return;
    }
    const list = Array.from(files);
    if (list.length === 0) return;

    // Optimistic per-file rows.
    const startBatch: UploadEntry[] = list.map((f, i) => ({
      id: `u-${Date.now()}-${i}`,
      filename: f.name,
      bytes: f.size,
      status: f.size > MAX_FILE_BYTES ? "error" : "pending",
      message: f.size > MAX_FILE_BYTES ? `Too large (max ${(MAX_FILE_BYTES / 1024 / 1024).toFixed(0)} MB)` : undefined,
    }));
    setUploads((prev) => [...startBatch, ...prev]);

    // REAL multipart upload — one POST per file to /api/evidence/upload, the
    // same backend path staff use. The file bytes are actually sent + persisted
    // as an EvidenceRecord on the backend partner Activity, so the IA can open
    // it from the verification queue. (Previously this sent only metadata.)
    startTransition(async () => {
      let okCount = 0;
      for (let i = 0; i < list.length; i++) {
        const f = list[i];
        const localId = startBatch[i].id;
        if (f.size > MAX_FILE_BYTES) continue;

        let ok = false;
        let message: string | undefined;
        try {
          const form = new FormData();
          form.append("file", f, f.name);
          form.append("activityId", activityId);
          form.append("kind", kind);
          const res = await fetch("/api/evidence/upload", {
            method: "POST",
            credentials: "include",
            headers: { ...csrfHeaders() }, // no Content-Type — browser sets the multipart boundary
            body: form,
          });
          const j = await res.json().catch(() => ({}));
          ok = res.ok && j.live !== false && !j.error;
          if (!ok) message = j.error || `Upload failed (${res.status})`;
        } catch {
          message = "Could not reach the server.";
        }
        if (ok) okCount += 1;
        setUploads((prev) =>
          prev.map((u) => (u.id === localId ? { ...u, status: ok ? "ok" : "error", message } : u)),
        );
      }
      if (okCount > 0) {
        pushToast({
          tone: "success",
          title: `${okCount} file${okCount === 1 ? "" : "s"} uploaded`,
          body: "Evidence is now pending CCEO confirmation.",
        });
      }
      router.refresh();
    });
  }

  return (
    <section className="flex flex-col gap-3">
      <div
        onDragOver={(e) => { e.preventDefault(); setOver(true); }}
        onDragLeave={() => setOver(false)}
        onDrop={(e) => {
          e.preventDefault();
          setOver(false);
          acceptFiles(e.dataTransfer.files);
        }}
        className={cn(
          "rounded-2xl border-2 border-dashed transition-colors p-5 flex flex-col sm:flex-row items-center gap-4",
          over ? "border-[var(--color-edify-primary)] bg-[var(--color-edify-soft)]/40" : "border-[var(--color-edify-border)] bg-white",
          !hasActivity && "opacity-60",
        )}
        aria-label="Bulk evidence upload"
      >
        <div className="grid place-items-center h-14 w-14 rounded-2xl bg-[var(--color-edify-soft)] text-[var(--color-edify-primary)] shrink-0">
          <Upload size={22} />
        </div>
        <div className="flex-1 min-w-0">
          <h3 className="text-body-lg font-extrabold tracking-tight">Drop evidence files here</h3>
          <p className="text-[12px] muted leading-snug mt-1 max-w-[60ch]">
            Upload attendance sheets, visit reports, photos, debriefs, and delivery notes. Files attach to the
            selected delivered activity below.
          </p>
          <div className="flex items-center gap-3 mt-2 text-caption muted">
            <span className="inline-flex items-center gap-1">
              <FileText size={11} /> PDF · JPG · PNG · DOCX
            </span>
            <span>•</span>
            <span className="inline-flex items-center gap-1">
              <CheckCircle2 size={11} className="text-emerald-600" /> Up to 25 MB per file
            </span>
          </div>
        </div>
        <input
          ref={fileInputRef}
          type="file"
          multiple
          hidden
          aria-hidden
          onChange={(e) => { if (e.target.files) acceptFiles(e.target.files); e.target.value = ""; }}
        />
        <button
          type="button"
          onClick={() => fileInputRef.current?.click()}
          disabled={!hasActivity || pending}
          className="inline-flex items-center gap-1.5 h-10 px-4 rounded-xl bg-[var(--color-edify-primary)] text-white text-body font-extrabold hover:bg-[var(--color-edify-dark)] disabled:opacity-50 disabled:cursor-not-allowed"
        >
          {pending ? <Loader2 size={14} className="animate-spin" /> : null}
          Choose files
        </button>
      </div>

      {/* Activity selector — single vs. multi vs. zero. */}
      {eligibleActivities.length === 0 ? (
        <p className="text-caption muted inline-flex items-center gap-1.5">
          <AlertCircle size={11} className="text-amber-600" />
          No activities awaiting evidence. Mark an activity Delivered first, then come back.
        </p>
      ) : (
        <div className="flex items-center gap-3 flex-wrap text-caption">
          {single ? (
            <p className="muted">Attaching to: <span className="font-semibold text-slate-800">{eligibleActivities[0].title}</span></p>
          ) : (
            <label className="inline-flex items-center gap-2">
              <span className="muted">Attach to:</span>
              <select
                value={activityId}
                onChange={(e) => setActivityId(e.target.value)}
                className="h-8 px-2 rounded-md border border-[var(--color-edify-border)] bg-white text-[11.5px] font-semibold"
              >
                {eligibleActivities.map((a) => (
                  <option key={a.id} value={a.id}>{a.title} · {a.schoolId}</option>
                ))}
              </select>
            </label>
          )}
          <label className="inline-flex items-center gap-2">
            <span className="muted">Evidence type:</span>
            <select
              value={kind}
              onChange={(e) => setKind(e.target.value)}
              className="h-8 px-2 rounded-md border border-[var(--color-edify-border)] bg-white text-[11.5px] font-semibold"
            >
              {EVIDENCE_KINDS.map((k) => (
                <option key={k.value} value={k.value}>{k.label}</option>
              ))}
            </select>
          </label>
        </div>
      )}

      {/* Per-file outcome list. Last batch on top. */}
      {uploads.length > 0 && (
        <ul className="flex flex-col gap-1.5">
          {uploads.slice(0, 8).map((u) => (
            <li
              key={u.id}
              className={cn(
                "rounded-md px-2.5 py-1.5 text-[11.5px] flex items-center justify-between gap-2 border",
                u.status === "ok"      && "border-emerald-200 bg-emerald-50/40",
                u.status === "error"   && "border-rose-200    bg-rose-50/40",
                u.status === "pending" && "border-[var(--color-edify-border)] bg-white",
              )}
            >
              <span className="font-mono truncate">{u.filename} <span className="muted">({Math.round(u.bytes / 1024)} KB)</span></span>
              <span className="inline-flex items-center gap-1 shrink-0">
                {u.status === "pending" && <Loader2 size={11} className="animate-spin" />}
                {u.status === "ok"      && <CheckCircle2 size={11} className="text-emerald-600" />}
                {u.status === "error"   && <AlertCircle size={11} className="text-rose-600" />}
                <span className={cn(
                  "font-semibold",
                  u.status === "ok" ? "text-emerald-700" : u.status === "error" ? "text-rose-700" : "text-slate-600",
                )}>
                  {u.status === "ok" ? "Uploaded" : u.status === "error" ? (u.message ?? "Failed") : "Uploading…"}
                </span>
              </span>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
