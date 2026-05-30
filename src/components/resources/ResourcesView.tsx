"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import {
  BookOpen,
  Video,
  FileText,
  GraduationCap,
  ShieldCheck,
  Wallet,
  ClipboardList,
  ChevronRight,
  Upload,
  X,
  Download,
  Trash2,
  type LucideIcon,
} from "lucide-react";
import type { EdifyRole } from "@/lib/auth-public";
import {
  RESOURCE_CATEGORIES,
  addResource,
  canUploadCategory,
  formatBytes,
  formatRelative,
  listResources,
  removeResource,
  subscribeResources,
  type ResourceCategory,
  type UploadedResource,
} from "@/lib/resources-store";
import { EmptyState } from "@/components/ui/EmptyState";

// Static seed rows (kept from the old page so first-load isn't empty).
// Seed items are read-only; only uploaded rows can be removed.
type SeedResource = {
  id:        string;
  title:     string;
  body:      string;
  category:  ResourceCategory;
  Icon:      LucideIcon;
  iconBg:    string;
  iconText:  string;
  href:      string;
};

const SEEDS: SeedResource[] = [
  { id: "r-1", title: "SSA Field Guide — 8 Interventions",     body: "What counts and what doesn't, with examples and worked scoring.", Icon: ShieldCheck,    iconBg: "bg-emerald-100", iconText: "text-emerald-700", href: "/help/ssa-field-guide",  category: "Field Guides"      },
  { id: "r-2", title: "Valid Visit Rulebook",                  body: "The five conditions that make a visit count for targets.",      Icon: BookOpen,       iconBg: "bg-sky-100",     iconText: "text-sky-700",     href: "/help/valid-visit",      category: "Field Guides"      },
  { id: "r-4", title: "Daily Debrief Workshop (video)",        body: "30-minute walkthrough of the new debrief form and engine.",     Icon: Video,          iconBg: "bg-violet-100",  iconText: "text-violet-700",  href: "/help/debrief-video",    category: "Training Material" },
  { id: "r-5", title: "Support-Review Checklist (HR + CPL)",   body: "Pre-PIP humane review — required before any escalation.",      Icon: ClipboardList,  iconBg: "bg-rose-100",    iconText: "text-rose-700",    href: "/help/support-review",   category: "Policies"          },
  { id: "r-6", title: "Cluster Training Toolkit",              body: "Lesson plans, facilitator notes, attendance sheets.",           Icon: GraduationCap,  iconBg: "bg-blue-100",    iconText: "text-blue-700",    href: "/help/cluster-training", category: "Training Material" },
  { id: "r-7", title: "Salesforce Logging — How-To",           body: "Salesforce IDs, evidence rules, return reasons.",               Icon: FileText,       iconBg: "bg-slate-100",   iconText: "text-slate-700",   href: "/help/salesforce",       category: "Policies"          },
  { id: "r-3", title: "Fund Request — Template & Approval Chain", body: "How to file, who approves, common rejections.",            Icon: Wallet,         iconBg: "bg-amber-100",   iconText: "text-amber-700",   href: "/help/fund-requests",    category: "Field Guides"      },
];

const CATEGORY_TONE: Record<ResourceCategory, { iconBg: string; iconText: string; Icon: LucideIcon }> = {
  "Field Guides":      { iconBg: "bg-emerald-100", iconText: "text-emerald-700", Icon: BookOpen      },
  "Policies":          { iconBg: "bg-rose-100",    iconText: "text-rose-700",    Icon: ShieldCheck   },
  "Training Material": { iconBg: "bg-violet-100",  iconText: "text-violet-700",  Icon: GraduationCap },
};

const MAX_UPLOAD_BYTES = 5 * 1024 * 1024; // 5 MB per file

export function ResourcesView({
  role,
  userName,
}: {
  role: EdifyRole;
  userName: string;
}) {
  const [uploads, setUploads] = useState<UploadedResource[]>([]);
  const [openUploader, setOpenUploader] = useState<ResourceCategory | null>(null);

  // Subscribe to the store so newly added or removed uploads re-render
  // without a route navigation. Migrate to useSyncExternalStore during
  // the React-19 sweep.
  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setUploads(listResources());
    return subscribeResources(() => setUploads(listResources()));
  }, []);

  return (
    <>
      {RESOURCE_CATEGORIES.map((cat) => {
        const seedRows = SEEDS.filter((r) => r.category === cat);
        const uploadRows = uploads.filter((r) => r.category === cat);
        const canUpload = canUploadCategory(role, cat);

        return (
          <section key={cat}>
            <header className="flex items-end justify-between gap-3 px-1 mb-1.5">
              <div>
                <h2 className="text-body font-extrabold uppercase tracking-wide muted">{cat}</h2>
                <p className="text-[11px] text-muted mt-0.5">
                  {uploadRows.length === 0
                    ? "No uploads yet."
                    : `${uploadRows.length} uploaded · ${seedRows.length} reference doc${seedRows.length === 1 ? "" : "s"}`}
                </p>
              </div>
              {canUpload && (
                <button
                  type="button"
                  onClick={() => setOpenUploader(cat)}
                  className="inline-flex items-center gap-1.5 h-8 px-3 rounded-lg bg-[var(--color-edify-primary)] text-white text-[11.5px] font-semibold hover:opacity-90"
                >
                  <Upload size={13} /> Upload
                </button>
              )}
            </header>

            <div className="card rounded-2xl divide-y divide-[var(--color-edify-divider)] overflow-hidden">
              {/* Uploaded rows first — they're the "fresh" content. */}
              {uploadRows.map((r) => (
                <UploadedRow key={r.id} resource={r} canRemove={r.uploadedByRole === role && r.uploadedByName === userName} />
              ))}

              {/* Seed rows below */}
              {seedRows.map((r) => (
                <Link
                  key={r.id}
                  href={r.href}
                  className="flex items-start gap-3 px-4 py-3.5 hover:bg-[var(--color-edify-soft)]/40"
                >
                  <span className={`h-9 w-9 rounded-md grid place-items-center shrink-0 ${r.iconBg} ${r.iconText}`}>
                    <r.Icon size={15} />
                  </span>
                  <div className="flex-1 min-w-0">
                    <div className="text-body font-extrabold tracking-tight">{r.title}</div>
                    <div className="text-[11px] muted">{r.body}</div>
                  </div>
                  <ChevronRight size={14} className="text-[var(--color-edify-muted)] shrink-0 self-center" />
                </Link>
              ))}

              {uploadRows.length === 0 && seedRows.length === 0 && (
                <EmptyState
                  Icon={Upload}
                  tone={cat === "Field Guides" ? "emerald" : cat === "Policies" ? "rose" : "violet"}
                  compact
                  bare
                  title={`No ${cat.toLowerCase()} yet`}
                  body={
                    canUpload
                      ? `Be the first to share a ${cat.toLowerCase().replace(/s$/, "")}. Everyone with access to Resources will see it.`
                      : "Check back soon — content for this category will appear here."
                  }
                  action={
                    canUpload ? (
                      <button
                        type="button"
                        onClick={() => setOpenUploader(cat)}
                        className="inline-flex items-center gap-1.5 h-9 px-3.5 rounded-lg bg-[var(--color-edify-primary)] text-white text-[12px] font-semibold hover:opacity-95"
                      >
                        <Upload size={13} /> Upload {cat.toLowerCase().replace(/s$/, "")}
                      </button>
                    ) : null
                  }
                />
              )}
            </div>
          </section>
        );
      })}

      {openUploader && (
        <UploadDialog
          category={openUploader}
          role={role}
          userName={userName}
          onClose={() => setOpenUploader(null)}
        />
      )}
    </>
  );
}

// ────────── Uploaded row (renders a stored UploadedResource) ──────────

function UploadedRow({ resource, canRemove }: { resource: UploadedResource; canRemove: boolean }) {
  const tone = CATEGORY_TONE[resource.category];
  return (
    <div className="flex items-start gap-3 px-4 py-3.5 hover:bg-[var(--color-edify-soft)]/40">
      <span className={`h-9 w-9 rounded-md grid place-items-center shrink-0 ${tone.iconBg} ${tone.iconText}`}>
        <tone.Icon size={15} />
      </span>
      <div className="flex-1 min-w-0">
        <div className="text-body font-extrabold tracking-tight truncate">{resource.title}</div>
        {resource.body && <div className="text-[11px] muted">{resource.body}</div>}
        <div className="text-caption text-muted mt-0.5 truncate">
          {resource.fileName} · {formatBytes(resource.fileSize)} · uploaded by {resource.uploadedByName} · {formatRelative(resource.uploadedAt)}
        </div>
      </div>
      <div className="flex items-center gap-1 shrink-0 self-center">
        {resource.dataUrl && (
          <a
            href={resource.dataUrl}
            download={resource.fileName}
            aria-label={`Download ${resource.fileName}`}
            className="grid place-items-center h-8 w-8 rounded-md text-secondary hover:bg-[var(--color-edify-soft)]"
          >
            <Download size={14} />
          </a>
        )}
        {canRemove && (
          <button
            type="button"
            onClick={() => {
              if (confirm(`Remove "${resource.title}"?`)) removeResource(resource.id);
            }}
            aria-label={`Remove ${resource.title}`}
            className="grid place-items-center h-8 w-8 rounded-md text-[#b3bcc5] hover:text-[#b42318] hover:bg-rose-50"
          >
            <Trash2 size={14} />
          </button>
        )}
      </div>
    </div>
  );
}

// ────────── Upload dialog ──────────

function UploadDialog({
  category,
  role,
  userName,
  onClose,
}: {
  category: ResourceCategory;
  role: EdifyRole;
  userName: string;
  onClose: () => void;
}) {
  const [title, setTitle] = useState("");
  const [body, setBody]   = useState("");
  const [file, setFile]   = useState<File | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy]   = useState(false);
  const inputRef = useRef<HTMLInputElement | null>(null);

  // Esc to close
  useEffect(() => {
    function onKey(e: KeyboardEvent) { if (e.key === "Escape") onClose(); }
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onClose]);

  const disabled = useMemo(() => !title.trim() || !file || busy, [title, file, busy]);

  async function submit() {
    setError(null);
    if (!file || !title.trim()) return;
    if (file.size > MAX_UPLOAD_BYTES) {
      setError(`File is too large. Max ${formatBytes(MAX_UPLOAD_BYTES)}.`);
      return;
    }
    setBusy(true);
    try {
      const dataUrl = await readAsDataUrl(file);
      addResource({
        title:          title.trim(),
        body:           body.trim(),
        category,
        fileName:       file.name,
        fileSize:       file.size,
        fileType:       file.type || "application/octet-stream",
        dataUrl,
        uploadedByName: userName,
        uploadedByRole: role,
      });
      onClose();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Upload failed. Try a smaller file.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label={`Upload ${category}`}
      className="fixed inset-0 z-50 flex items-start sm:items-center justify-center p-4 bg-black/40"
      onClick={onClose}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        className="w-full max-w-[480px] rounded-2xl bg-white shadow-[0_24px_60px_-20px_rgba(15,23,32,0.35)] overflow-hidden"
      >
        <header className="flex items-center justify-between gap-3 px-5 py-4 border-b border-[var(--color-edify-divider)]">
          <div>
            <div className="text-body-lg font-extrabold tracking-tight">Upload to {category}</div>
            <div className="text-[11px] muted mt-0.5">
              Visible to everyone with access to Resources.
            </div>
          </div>
          <button
            type="button"
            aria-label="Close"
            onClick={onClose}
            className="grid place-items-center h-8 w-8 rounded-md text-[#b3bcc5] hover:text-secondary hover:bg-[#f4f6f8]"
          >
            <X size={16} />
          </button>
        </header>

        <div className="px-5 py-4 space-y-3.5">
          <label className="block">
            <div className="text-[11px] font-bold uppercase tracking-wide muted mb-1">Title</div>
            <input
              type="text"
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              placeholder={category === "Policies" ? "e.g. Cluster Visit Policy v3" : "Short, scannable title"}
              className="w-full h-10 px-3 rounded-lg border border-[var(--color-edify-border)] text-[13px] focus:outline-none focus:ring-2 focus:ring-[var(--color-edify-primary)]/30"
            />
          </label>

          <label className="block">
            <div className="text-[11px] font-bold uppercase tracking-wide muted mb-1">Description (optional)</div>
            <textarea
              value={body}
              onChange={(e) => setBody(e.target.value)}
              placeholder="One line on what this is and when to use it."
              rows={2}
              className="w-full px-3 py-2 rounded-lg border border-[var(--color-edify-border)] text-[13px] focus:outline-none focus:ring-2 focus:ring-[var(--color-edify-primary)]/30"
            />
          </label>

          <div>
            <div className="text-[11px] font-bold uppercase tracking-wide muted mb-1">File</div>
            <input
              ref={inputRef}
              type="file"
              accept=".pdf,.doc,.docx,.ppt,.pptx,.xls,.xlsx,.txt,.mp4,.mov,.png,.jpg,.jpeg"
              onChange={(e) => setFile(e.target.files?.[0] ?? null)}
              className="block w-full text-[12px] file:mr-3 file:py-2 file:px-3 file:rounded-md file:border-0 file:bg-[var(--color-edify-soft)] file:text-[var(--color-edify-primary)] file:font-semibold file:cursor-pointer"
            />
            {file && (
              <div className="text-[11px] muted mt-1.5">
                {file.name} · {formatBytes(file.size)}
              </div>
            )}
            <div className="text-caption text-muted mt-1">
              Max {formatBytes(MAX_UPLOAD_BYTES)}. PDFs, Office docs, images, and short video clips supported.
            </div>
          </div>

          {error && (
            <div className="text-[11.5px] text-rose-700 bg-rose-50 border border-rose-200 rounded-md px-3 py-2">
              {error}
            </div>
          )}
        </div>

        <footer className="flex items-center justify-end gap-2 px-5 py-3 border-t border-[var(--color-edify-divider)] bg-[var(--color-edify-soft)]/30">
          <button
            type="button"
            onClick={onClose}
            className="h-9 px-3 rounded-lg text-body font-semibold text-secondary hover:bg-white"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={submit}
            disabled={disabled}
            className="h-9 px-4 rounded-lg bg-[var(--color-edify-primary)] text-white text-body font-semibold disabled:opacity-50"
          >
            {busy ? "Uploading…" : "Upload resource"}
          </button>
        </footer>
      </div>
    </div>
  );
}

function readAsDataUrl(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload  = () => resolve(String(reader.result ?? ""));
    reader.onerror = () => reject(new Error("Could not read file."));
    reader.readAsDataURL(file);
  });
}
