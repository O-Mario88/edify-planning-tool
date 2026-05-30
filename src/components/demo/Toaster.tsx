"use client";

import { useEffect } from "react";
import { CheckCircle2, AlertTriangle, Info, XCircle, X } from "lucide-react";
import { useDemoStore, type Toast } from "@/components/demo/DemoStore";
import { cn } from "@/lib/utils";

const ICON = {
  success: CheckCircle2,
  warning: AlertTriangle,
  error:   XCircle,
  info:    Info,
} as const;

const TONE = {
  success: { bg: "bg-emerald-50", border: "border-emerald-200", icon: "text-emerald-600" },
  warning: { bg: "bg-amber-50",   border: "border-amber-200",   icon: "text-amber-600"   },
  error:   { bg: "bg-rose-50",    border: "border-rose-200",    icon: "text-rose-600"    },
  info:    { bg: "bg-sky-50",     border: "border-sky-200",     icon: "text-sky-600"     },
} as const;

export function Toaster() {
  const { toasts, dismissToast } = useDemoStore();
  return (
    <div className="fixed top-4 right-4 z-[60] flex flex-col gap-2 max-w-[360px] w-[calc(100vw-32px)] sm:w-auto pointer-events-none">
      {toasts.map((t) => <ToastCard key={t.id} toast={t} onDismiss={() => dismissToast(t.id)} />)}
    </div>
  );
}

function ToastCard({ toast, onDismiss }: { toast: Toast; onDismiss: () => void }) {
  const Icon = ICON[toast.tone];
  const tone = TONE[toast.tone];

  useEffect(() => {
    if (!toast.ttl) return;
    const handle = window.setTimeout(onDismiss, toast.ttl);
    return () => window.clearTimeout(handle);
  }, [toast.ttl, onDismiss]);

  return (
    <div
      role="status"
      className={cn(
        "pointer-events-auto rounded-xl border shadow-lg px-3 py-2.5 flex items-start gap-2.5 animate-in slide-in-from-right-4 fade-in duration-200",
        tone.bg, tone.border,
      )}
    >
      <Icon size={14} className={cn("mt-0.5 shrink-0", tone.icon)} />
      <div className="flex-1 min-w-0">
        <div className="text-body font-extrabold tracking-tight">{toast.title}</div>
        {toast.body && <div className="text-[11px] muted leading-snug mt-0.5">{toast.body}</div>}
      </div>
      <button
        type="button"
        onClick={onDismiss}
        className="h-6 w-6 rounded-md grid place-items-center hover:bg-black/5"
        aria-label="Dismiss"
      >
        <X size={11} className="text-[var(--color-edify-muted)]" />
      </button>
    </div>
  );
}
