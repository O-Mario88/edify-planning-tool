"use client";

// GlassDatePicker — a custom calendar popover with a dark frosted-glass theme.
// Replaces the browser-native <input type=date>. Controlled: value is an
// ISO "YYYY-MM-DD" string, onChange returns the same. Monday-first grid,
// month nav, today marker, dimmed adjacent-month days.

import { useEffect, useMemo, useRef, useState } from "react";
import { CalendarDays, ChevronLeft, ChevronRight, X } from "lucide-react";
import { cn } from "@/lib/utils";

const WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
const MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"];

function pad(n: number) { return String(n).padStart(2, "0"); }
function toIso(y: number, m: number, d: number) { return `${y}-${pad(m + 1)}-${pad(d)}`; }
function parseIso(v?: string): { y: number; m: number; d: number } | null {
  if (!v) return null;
  const mm = /^(\d{4})-(\d{2})-(\d{2})/.exec(v);
  if (!mm) return null;
  return { y: Number(mm[1]), m: Number(mm[2]) - 1, d: Number(mm[3]) };
}
function prettyIso(v?: string): string {
  const p = parseIso(v);
  return p ? `${pad(p.d)}/${pad(p.m + 1)}/${p.y}` : "";
}

type Cell = { day: number; inMonth: boolean; iso: string };

function monthGrid(year: number, month: number): Cell[] {
  const first = new Date(year, month, 1);
  const startOffset = (first.getDay() + 6) % 7; // Monday-first
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
  while (cells.length % 7 !== 0 || cells.length < 42) {
    const nm = month === 11 ? 0 : month + 1;
    const ny = month === 11 ? year + 1 : year;
    cells.push({ day: nd, inMonth: false, iso: toIso(ny, nm, nd) });
    nd++;
    if (cells.length >= 42) break;
  }
  return cells;
}

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
  const rootRef = useRef<HTMLDivElement>(null);

  const today = new Date();
  const todayIso = toIso(today.getFullYear(), today.getMonth(), today.getDate());
  const sel = parseIso(value);
  const [view, setView] = useState(() => sel ?? { y: today.getFullYear(), m: today.getMonth(), d: today.getDate() });

  // Re-centre the view on the selected value when it changes externally.
  useEffect(() => {
    if (sel) setView((v) => (v.y === sel.y && v.m === sel.m ? v : { ...sel }));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [value]);

  useEffect(() => {
    if (!open) return;
    function onDoc(e: MouseEvent) {
      if (rootRef.current && !rootRef.current.contains(e.target as Node)) setOpen(false);
    }
    function onKey(e: KeyboardEvent) { if (e.key === "Escape") setOpen(false); }
    document.addEventListener("mousedown", onDoc);
    document.addEventListener("keydown", onKey);
    return () => { document.removeEventListener("mousedown", onDoc); document.removeEventListener("keydown", onKey); };
  }, [open]);

  const cells = useMemo(() => monthGrid(view.y, view.m), [view.y, view.m]);

  function shiftMonth(delta: number) {
    setView((v) => {
      const m = v.m + delta;
      const y = v.y + Math.floor(m / 12);
      const nm = ((m % 12) + 12) % 12;
      return { ...v, y, m: nm };
    });
  }
  function pick(iso: string) {
    onChange(iso);
    setOpen(false);
  }

  return (
    <div ref={rootRef} className={cn("relative inline-block", className)}>
      {/* Trigger */}
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className={cn(
          "inline-flex items-center gap-2 h-9 px-2.5 rounded-lg border bg-white text-[12px] transition-colors",
          value ? "border-[var(--color-edify-border)] text-[var(--color-edify-text)]" : "border-[var(--color-edify-border)] text-[var(--color-edify-muted)]",
          open && "ring-2 ring-[var(--color-edify-primary)]/30",
        )}
      >
        <CalendarDays size={13} className="text-[var(--color-edify-primary)]" />
        <span className="tabular">{prettyIso(value) || placeholder}</span>
      </button>

      {open && (
        <div
          role="dialog"
          aria-label="Choose a date"
          className="absolute z-50 mt-2 w-[300px] rounded-3xl border border-white/15 p-4 text-white shadow-2xl backdrop-blur-2xl"
          style={{ backgroundColor: "rgba(15, 23, 42, 0.74)" }}
        >
          {/* Header */}
          <div className="flex items-center justify-between mb-3">
            <div className="text-[15px] font-extrabold tracking-tight inline-flex items-center gap-1.5">
              <CalendarDays size={15} className="text-white/70" />
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
              <div key={w} className="text-center text-[10.5px] font-semibold text-white/45 py-1">{w}</div>
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
                    !c.inMonth && "text-white/30",
                    c.inMonth && !isSel && "text-white/90 hover:bg-white/12",
                    isSel && "bg-[var(--color-edify-primary)] text-white font-extrabold shadow-lg",
                    !isSel && isToday && "ring-1 ring-white/40",
                    disabled && "opacity-30 cursor-not-allowed hover:bg-transparent",
                  )}
                >
                  {c.day}
                </button>
              );
            })}
          </div>

          {/* Footer */}
          <div className="flex items-center justify-between mt-3 pt-3 border-t border-white/10">
            <button type="button" onClick={() => { onChange(""); setOpen(false); }} className="inline-flex items-center gap-1 text-[12px] font-semibold text-white/60 hover:text-white">
              <X size={12} /> Clear
            </button>
            <button type="button" onClick={() => pick(todayIso)} className="text-[12px] font-semibold text-[var(--color-edify-accent,#7dd3fc)] hover:underline" style={{ color: "#93c5fd" }}>
              Today
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

function CalBtn({ onClick, label, children }: { onClick: () => void; label: string; children: React.ReactNode }) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-label={label}
      className="grid place-items-center h-8 w-8 rounded-xl border border-white/15 bg-white/5 text-white/80 hover:bg-white/15 transition-colors"
    >
      {children}
    </button>
  );
}
