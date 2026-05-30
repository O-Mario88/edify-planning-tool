"use client";

import { useState } from "react";
import {
  Bed,
  ChevronDown,
  Home,
  MessageSquare,
  Monitor,
  Printer,
  Save,
  Send,
  Truck,
  Users,
  Utensils,
  X,
  type LucideIcon,
} from "lucide-react";
import { adminBudgetCategories, type AdminBudgetCategory } from "@/lib/country-fund-approvals-mock";
import { cn } from "@/lib/utils";

const CAT_ICON: Record<AdminBudgetCategory["icon"], LucideIcon> = {
  home:     Home,
  printer:  Printer,
  monitor:  Monitor,
  truck:    Truck,
  bed:      Bed,
  utensils: Utensils,
  users:    Users,
  message:  MessageSquare,
};

// Right-side slide-in drawer for creating a country-level admin fund
// request. Triggered from the header's "Create Admin Fund Request"
// button. All fields mirror the reference design exactly.
export function CreateAdminFundRequestDrawer({
  open,
  onClose,
}: {
  open:    boolean;
  onClose: () => void;
}) {
  const [selectedCat, setSelectedCat] = useState<string | null>(null);
  const [notes, setNotes] = useState("");

  if (!open) return null;

  return (
    <>
      {/* Backdrop */}
      <div
        className="fixed inset-0 bg-slate-900/30 backdrop-blur-sm z-40 animate-[fade-in_200ms_ease-out]"
        onClick={onClose}
        aria-hidden
      />

      {/* Drawer */}
      <aside
        className="fixed top-0 right-0 z-50 h-screen w-full sm:w-[420px] bg-white shadow-[0_24px_60px_-12px_rgba(15,23,32,0.30)] overflow-y-auto"
        style={{ animation: "slide-in-right 280ms cubic-bezier(0.2, 0.6, 0.2, 1)" }}
        role="dialog"
        aria-modal="true"
        aria-labelledby="create-admin-request-title"
      >
        {/* Header */}
        <header className="sticky top-0 z-10 bg-white/95 backdrop-blur border-b border-[var(--color-edify-border)] px-5 py-4 flex items-start justify-between gap-3">
          <div className="min-w-0">
            <h2 id="create-admin-request-title" className="text-[16px] font-extrabold tracking-tight">
              Create Admin Fund Request
            </h2>
            <p className="text-[11.5px] muted leading-snug mt-1">
              Create a country-level admin budget request.
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close drawer"
            className="w-9 h-9 rounded-lg grid place-items-center text-slate-500 hover:bg-slate-100 transition-colors shrink-0"
          >
            <X size={16} />
          </button>
        </header>

        {/* Body */}
        <div className="px-5 py-5 space-y-4">
          {/* Request Title */}
          <Field label="Request Title" required>
            <input
              type="text"
              placeholder="e.g., Office Rent for June 2025"
              className="w-full h-10 px-3 rounded-xl border border-[var(--color-edify-border)] bg-white text-body placeholder:text-slate-400 focus:outline-none focus:border-emerald-400 focus:ring-2 focus:ring-emerald-100 transition-colors"
            />
          </Field>

          {/* Budget Category dropdown + quick chips */}
          <Field label="Budget Category" required>
            <button
              type="button"
              className="w-full h-10 px-3 rounded-xl border border-[var(--color-edify-border)] bg-white flex items-center justify-between gap-2 text-body text-slate-400 hover:bg-slate-50 transition-colors"
            >
              <span>{selectedCat ?? "Select category"}</span>
              <ChevronDown size={14} className="text-slate-400" />
            </button>

            <div className="mt-2 grid grid-cols-2 gap-2">
              {adminBudgetCategories.map((c) => {
                const Icon = CAT_ICON[c.icon];
                const active = selectedCat === c.label;
                return (
                  <button
                    key={c.key}
                    type="button"
                    onClick={() => setSelectedCat(active ? null : c.label)}
                    className={cn(
                      "h-10 px-2.5 rounded-xl border flex items-center gap-2 text-[11.5px] font-semibold transition-all",
                      active
                        ? "border-emerald-400 bg-emerald-50 text-emerald-800 shadow-[0_4px_12px_-4px_rgba(16,185,129,0.30)]"
                        : "border-[var(--color-edify-border)] bg-white text-slate-700 hover:bg-slate-50 hover:border-slate-300",
                    )}
                  >
                    <span className={cn(
                      "w-6 h-6 rounded-md grid place-items-center shrink-0",
                      active ? "bg-emerald-200 text-emerald-700" : "bg-slate-100 text-slate-600",
                    )}>
                      <Icon size={12} />
                    </span>
                    {c.label}
                  </button>
                );
              })}
            </div>
          </Field>

          {/* Amount */}
          <Field label="Amount (UGX)" required>
            <div className="flex">
              <span className="inline-flex items-center px-3 rounded-l-xl border border-r-0 border-[var(--color-edify-border)] bg-slate-50 text-[12px] font-extrabold text-slate-600">
                UGX
              </span>
              <input
                type="text"
                placeholder="Enter amount"
                className="flex-1 h-10 px-3 rounded-r-xl border border-[var(--color-edify-border)] bg-white text-body tabular placeholder:text-slate-400 focus:outline-none focus:border-emerald-400 focus:ring-2 focus:ring-emerald-100 transition-colors"
              />
            </div>
          </Field>

          {/* Period */}
          <Field label="Period" required>
            <button
              type="button"
              className="w-full h-10 px-3 rounded-xl border border-[var(--color-edify-border)] bg-white flex items-center justify-between gap-2 text-body text-slate-400 hover:bg-slate-50 transition-colors"
            >
              <span>Select period</span>
              <ChevronDown size={14} className="text-slate-400" />
            </button>
          </Field>

          {/* Region / Office */}
          <Field label="Region / Office" required>
            <button
              type="button"
              className="w-full h-10 px-3 rounded-xl border border-[var(--color-edify-border)] bg-white flex items-center justify-between gap-2 text-body text-slate-400 hover:bg-slate-50 transition-colors"
            >
              <span>Select region / office</span>
              <ChevronDown size={14} className="text-slate-400" />
            </button>
          </Field>

          {/* Notes */}
          <Field label="Notes">
            <div className="relative">
              <textarea
                value={notes}
                onChange={(e) => setNotes(e.target.value.slice(0, 500))}
                placeholder="Provide details about this request…"
                rows={4}
                className="w-full px-3 py-2 rounded-xl border border-[var(--color-edify-border)] bg-white text-body placeholder:text-slate-400 focus:outline-none focus:border-emerald-400 focus:ring-2 focus:ring-emerald-100 transition-colors resize-none"
              />
              <span className="absolute bottom-2 right-3 text-[10px] muted font-semibold tabular pointer-events-none">
                {notes.length} / 500
              </span>
            </div>
          </Field>
        </div>

        {/* Footer actions */}
        <footer className="sticky bottom-0 z-10 bg-white/95 backdrop-blur border-t border-[var(--color-edify-border)] px-5 py-4 space-y-2">
          <div className="grid grid-cols-2 gap-2">
            <button
              type="button"
              className="inline-flex items-center justify-center gap-1.5 h-10 px-4 rounded-xl bg-white border border-[var(--color-edify-border)] hover:bg-slate-50 text-body font-semibold text-slate-700 transition-colors"
            >
              <Save size={13} />
              Save Draft
            </button>
            <button
              type="button"
              className="btn btn-primary inline-flex items-center justify-center gap-1.5 h-10 px-4 rounded-xl text-body font-extrabold"
            >
              <Send size={13} />
              Submit Request
            </button>
          </div>
          <p className="text-caption muted leading-snug flex items-start gap-1">
            <Save size={10} className="shrink-0 mt-0.5" />
            Drafts are saved automatically. You can edit and submit later.
          </p>
        </footer>
      </aside>

      <style jsx global>{`
        @keyframes fade-in {
          from { opacity: 0; }
          to   { opacity: 1; }
        }
        @keyframes slide-in-right {
          from { transform: translateX(20px); opacity: 0; }
          to   { transform: translateX(0);    opacity: 1; }
        }
      `}</style>
    </>
  );
}

function Field({
  label,
  required,
  children,
}: {
  label: string;
  required?: boolean;
  children: React.ReactNode;
}) {
  return (
    <div>
      <label className="block text-[11.5px] font-bold text-slate-700 mb-1.5">
        {label}
        {required && <span className="text-rose-500 ml-0.5">*</span>}
      </label>
      {children}
    </div>
  );
}
