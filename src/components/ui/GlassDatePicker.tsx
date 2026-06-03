"use client";

// Theme-aware calendar date picker — replaces the browser-native
// <input type=date> app-wide. The popover uses the design-system tokens, so it
// renders solid-light in Light, solid-dark in Dark, and frosted-translucent in
// Glass (the glass look only appears under the .glass theme). The popover is
// portaled to <body> with fixed positioning so it is never clipped by a card's
// overflow, and flips above the trigger when there isn't room below.

import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { CalendarDays, ChevronLeft, ChevronRight, X } from "lucide-react";
import { cn } from "@/lib/utils";

const WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
const MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"];

function pad(n: number) { return String(n).padStart(2, "0"); }
function toIso(y: number, m: number, d: number) { return `${y}-${pad(m + 1)}-${pad(d)}`; }
function parseIso(v?: string): { y: number; m: number; d: number } | null {
  if (!v) return null;
  const mm = /^(\d{4})-(\d{2})-(\d{2})/.exec(v);
  return mm ? { y: Number(mm[1]), m: Number(mm[2]) - 1, d: Number(mm[3]) } : null;
}
function prettyIso(v?: string): string {
  const p = parseIso(v);
  return p ? `${pad(p.d)}/${pad(p.m + 1)}/${p.y}` : "";
}

type Cell = { day: number; inMonth: boolean; iso: string };

function monthGrid(year: number, month: number): Cell[] {
  const startOffset = (new Date(year, month, 1).getDay() + 6) % 7; // Monday-first
  const daysInMonth = new Date(year, month + 1, 0).getDate();
  const daysInPrev = new Date(year, month, 0).getDate();
  const cells: Cell[] = [];
  for (let i = startOffset - 1; i >= 0; i--) {
    const d = daysInPrev - i;
    const pm = month === 0 ? 11 : month - 1;
    const py = month === 0 ? year - 1 : year;
    cells.push({ day: d, inMonth: false, iso: toIso(py, pm, d) });
  }
  for (let d = 1; d <= daysInMonth; d++) cells.push({ day: d, inMonth: true, iso: toIso(year, month, d) });
  let nd = 1;
  while (cells.length < 42) {
    const nm = month === 11 ? 0 : month + 1;
    const ny = month === 11 ? year + 1 : year;
    cells.push({ day: nd, inMonth: false, iso: toIso(ny, nm, nd) });
    nd++;
  }
  return cells;
}

const POPOVER_W = 300;
const POPOVER_H = 372;

export function GlassDatePicker({
  value,
  onChange,
  placeholder = "dd/mm/yyyy",
  className,
  min,
}: {
  value?: string;
  onChange: (iso: string) => void;
  placeholder?: string;
  className?: string;
  /** Optional ISO lower bound — earlier days are disabled. */
  min?: string;
}) {
  const [open, setOpen] = useState(false);
  const [mounted, setMounted] = useState(false);
  const [pos, setPos] = useState<{ top: number; left: number }>({ top: 0, left: 0 });
  const triggerRef = useRef<HTMLButtonElement>(null);
  const popRef = useRef<HTMLDivElement>(null);

  useEffect(() => setMounted(true), []);

  const today = new Date();
  const todayIso = toIso(today.getFullYear(), today.getMonth(), today.getDate());
  const sel = parseIso(value);
  const [view, setView] = useState(() => sel ?? { y: today.getFullYear(), m: today.getMonth(), d: today.getDate() });

  useEffect(() => {
    if (sel) setView((v) => (v.y === sel.y && v.m === sel.m ? v : { ...sel }));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [value]);

  function reposition() {
    const t = triggerRef.current;
    if (!t) return;
    const r = t.getBoundingClientRect();
    const below = r.bottom + 6;
    const flipUp = below + POPOVER_H > window.innerHeight && r.top - POPOVER_H - 6 > 0;
    const top = flipUp ? r.top - POPOVER_H - 6 : below;
    const left = Math.max(8, Math.min(r.left, window.innerWidth - POPOVER_W - 8));
    setPos({ top, left });
  }

  useLayoutEffect(() => {
    if (open) reposition();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  useEffect(() => {
    if (!open) return;
    function onScrollResize() { reposition(); }
    function onDoc(e: MouseEvent) {
      const t = e.target as Node;
      if (triggerRef.current?.contains(t) || popRef.current?.contains(t)) return;
      setOpen(false);
    }
    function onKey(e: KeyboardEvent) { if (e.key === "Escape") setOpen(false); }
    window.addEventListener("scroll", onScrollResize, true);
    window.addEventListener("resize", onScrollResize);
    document.addEventListener("mousedown", onDoc);
    document.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("scroll", onScrollResize, true);
      window.removeEventListener("resize", onScrollResize);
      document.removeEventListener("mousedown", onDoc);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  const cells = useMemo(() => monthGrid(view.y, view.m), [view.y, view.m]);

  function shiftMonth(delta: number) {
    setView((v) => {
      const m = v.m + delta;
      const y = v.y + Math.floor(m / 12);
      return { ...v, y, m: ((m % 12) + 12) % 12 };
    });
  }
  function pick(iso: string) { onChange(iso); setOpen(false); }

  const popover = open && mounted ? createPortal(
    <div
      ref={popRef}
      role="dialog"
      aria-label="Choose a date"
      className="premium-popover fixed z-[1000] rounded-2xl p-4 text-[var(--text-primary)]"
      style={{ top: pos.top, left: pos.left, width: POPOVER_W }}
    >
      {/* Header */}
      <div className="flex items-center justify-between mb-3">
        <div className="text-[15px] font-extrabold tracking-tight inline-flex items-center gap-1.5">
          <CalendarDays size={15} className="text-[var(--text-muted)]" />
          {MONTHS[view.m]} {view.y}
        </div>
        <div className="flex items-center gap-1">
          <CalBtn onClick={() => shiftMonth(-1)} label="Previous month"><ChevronLeft size={16} /></CalBtn>
          <CalBtn onClick={() => shiftMonth(1)} label="Next month"><ChevronRight size={16} /></CalBtn>
        </div>
      </div>

      {/* Weekday headers */}
      <div className="grid grid-cols-7 gap-1 mb-1">
        {WEEKDAYS.map((w) => (
          <div key={w} className="text-center text-[10.5px] font-semibold text-[var(--text-muted)] py-1">{w}</div>
        ))}
      </div>

      {/* Day grid */}
      <div className="grid grid-cols-7 gap-1">
        {cells.map((c, i) => {
          const isSel = !!value && c.iso === value;
          const isToday = c.iso === todayIso;
          const disabled = !!min && c.iso < min;
          return (
            <button
              key={`${c.iso}-${i}`}
              type="button"
              disabled={disabled}
              onClick={() => pick(c.iso)}
              className={cn(
                "h-9 w-9 mx-auto grid place-items-center rounded-full text-[13px] tabular transition-colors",
                !c.inMonth && "text-[var(--text-muted)] opacity-60",
                c.inMonth && !isSel && "text-[var(--text-primary)] hover:bg-[var(--surface-hover)]",
                isSel && "bg-[var(--color-edify-primary)] text-white font-extrabold shadow-md",
                !isSel && isToday && "ring-1 ring-[var(--color-edify-primary)]/50",
                disabled && "opacity-30 cursor-not-allowed hover:bg-transparent",
              )}
            >
              {c.day}
            </button>
          );
        })}
      </div>

      {/* Footer */}
      <div className="flex items-center justify-between mt-3 pt-3 border-t border-[var(--border-card)]">
        <button type="button" onClick={() => { onChange(""); setOpen(false); }} className="inline-flex items-center gap-1 text-[12px] font-semibold text-[var(--text-muted)] hover:text-[var(--text-primary)]">
          <X size={12} /> Clear
        </button>
        <button type="button" onClick={() => pick(todayIso)} className="text-[12px] font-semibold text-[var(--color-edify-primary)] hover:underline">
          Today
        </button>
      </div>
    </div>,
    document.body,
  ) : null;

  return (
    <div className={cn("relative inline-block", className)}>
      <button
        ref={triggerRef}
        type="button"
        onClick={() => setOpen((o) => !o)}
        className={cn(
          "inline-flex items-center gap-2 h-9 px-2.5 rounded-lg border bg-[var(--surface-1,#fff)] text-[12px] transition-colors",
          value ? "border-[var(--color-edify-border)] text-[var(--color-edify-text)]" : "border-[var(--color-edify-border)] text-[var(--color-edify-muted)]",
          open && "ring-2 ring-[var(--color-edify-primary)]/30",
        )}
      >
        <CalendarDays size={13} className="text-[var(--color-edify-primary)]" />
        <span className="tabular">{prettyIso(value) || placeholder}</span>
      </button>
      {popover}
    </div>
  );
}

function CalBtn({ onClick, label, children }: { onClick: () => void; label: string; children: React.ReactNode }) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-label={label}
      className="grid place-items-center h-8 w-8 rounded-xl border border-[var(--border-card)] bg-[var(--surface-hover)] text-[var(--text-secondary)] hover:bg-[var(--surface-2)] transition-colors"
    >
      {children}
    </button>
  );
}
