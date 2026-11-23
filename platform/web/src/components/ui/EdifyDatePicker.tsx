'use client';

/**
 * EdifyDatePicker & EdifyDateRangePicker — Unified Enterprise Date Picker
 * (Sections 10 & 11).
 *
 * Non-negotiable UX rules:
 *   1. ZERO visible chevron on the date trigger field.
 *   2. Entire field (left calendar icon, date/placeholder text, empty interior
 *      space, right padding) is ONE single accessible clickable button surface.
 *   3. No nested interactive elements inside the trigger button.
 *   4. Timezone-safe YYYY-MM-DD arithmetic with Uganda FY2027 (Oct 1 – Sep 30)
 *      awareness and opt-in planning scheduling policies (Sundays/holidays/leave
 *      disabled; Saturdays enabled).
 */
import { CalendarDays, ChevronLeft, ChevronRight } from 'lucide-react';
import { useEffect, useId, useMemo, useRef, useState } from 'react';

import {
  MONTHS_FULL,
  MONTHS_SHORT,
  WEEKDAYS_SHORT,
  addDays,
  addMonths,
  buildMonthGrid,
  compareIso,
  evaluateDayAvailability,
  formatDisplayDate,
  kampalaTodayIso,
  parseIso,
  rangePresets,
  ugandaFiscalYear,
} from '@/lib/datePicker';
import type { DatePolicy } from '@/lib/datePicker';

export interface EdifyDatePickerProps {
  /** Controlled YYYY-MM-DD value. Leave undefined for uncontrolled form usage. */
  value?: string;
  /** Initial YYYY-MM-DD value for uncontrolled usage. */
  defaultValue?: string;
  onChange?: (iso: string) => void;
  /** Optional hidden input name for standard HTML form submission. */
  name?: string;
  id?: string;
  label?: string;
  placeholder?: string;
  displayStyle?: 'medium' | 'weekday';
  policy?: DatePolicy;
  min?: string;
  max?: string;
  required?: boolean;
  disabled?: boolean;
  /** Show Today / Tomorrow quick actions in the calendar footer. */
  showQuickActions?: boolean;
  /** Show Uganda FY indicator in calendar footer (e.g. FY2027). */
  showFiscalYear?: boolean;
  /** Visual size preset. */
  size?: 'sm' | 'md' | 'lg';
  align?: 'left' | 'right';
  className?: string;
}

export function EdifyDatePicker({
  value: controlled,
  defaultValue = '',
  onChange,
  name,
  id,
  label = 'Select date',
  placeholder = 'Select date',
  displayStyle = 'medium',
  policy,
  min,
  max,
  required = false,
  disabled = false,
  showQuickActions = true,
  showFiscalYear = false,
  size = 'md',
  align = 'left',
  className = '',
}: EdifyDatePickerProps) {
  const autoId = useId();
  const fieldId = id ?? `edify-date-${autoId}`;
  const isControlled = controlled !== undefined;
  const [internal, setInternal] = useState(defaultValue);
  const current = isControlled ? controlled : internal;

  const today = useMemo(() => kampalaTodayIso(), []);
  const effectivePolicy = useMemo<DatePolicy>(
    () => ({
      ...policy,
      min: min ?? policy?.min,
      max: max ?? policy?.max,
    }),
    [policy, min, max],
  );

  const initialParts = parseIso(current) ?? parseIso(today)!;
  const [open, setOpen] = useState(false);
  const [view, setView] = useState<{ y: number; m: number }>({ y: initialParts.y, m: initialParts.m });
  const [pickingMonthYear, setPickingMonthYear] = useState(false);
  const [focusedIso, setFocusedIso] = useState(current || today);
  const rootRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return undefined;
    const onPointer = (e: MouseEvent) => {
      if (!rootRef.current?.contains(e.target as Node)) {
        setOpen(false);
        setPickingMonthYear(false);
      }
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        setOpen(false);
        setPickingMonthYear(false);
      }
    };
    document.addEventListener('mousedown', onPointer);
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('mousedown', onPointer);
      document.removeEventListener('keydown', onKey);
    };
  }, [open]);

  const toggleOpen = () => {
    if (disabled) return;
    if (!open) {
      const target = parseIso(current) ?? parseIso(today)!;
      setView({ y: target.y, m: target.m });
      setFocusedIso(current || today);
      setPickingMonthYear(false);
    }
    setOpen((prev) => !prev);
  };

  const commit = (iso: string) => {
    if (iso) {
      const avail = evaluateDayAvailability(iso, effectivePolicy);
      if (avail.disabled) return;
    }
    if (!isControlled) setInternal(iso);
    onChange?.(iso);
    setOpen(false);
    setPickingMonthYear(false);
  };

  const grid = useMemo(() => buildMonthGrid(view.y, view.m), [view.y, view.m]);
  const fyInfo = useMemo(() => ugandaFiscalYear(current || today), [current, today]);
  const years = useMemo(() => {
    const startY = view.y - 4;
    return Array.from({ length: 12 }, (_, idx) => startY + idx);
  }, [view.y]);

  const handleGridKeyDown = (e: React.KeyboardEvent) => {
    const stepMap: Record<string, number> = {
      ArrowLeft: -1,
      ArrowRight: 1,
      ArrowUp: -7,
      ArrowDown: 7,
    };
    const delta = stepMap[e.key];
    if (delta !== undefined) {
      e.preventDefault();
      const next = addDays(focusedIso, delta);
      const parsed = parseIso(next);
      if (parsed) {
        setFocusedIso(next);
        setView({ y: parsed.y, m: parsed.m });
      }
    } else if (e.key === 'Enter' || e.key === ' ') {
      e.preventDefault();
      commit(focusedIso);
    }
  };

  const sizeClass =
    size === 'lg'
      ? 'h-12 px-4 text-[15px] rounded-[12px]'
      : size === 'sm'
        ? 'h-9 px-3 text-[13px] rounded-[8px]'
        : 'h-10 px-3.5 text-[14px] rounded-[10px]';

  const displayValue = current ? formatDisplayDate(current, displayStyle) : '';

  return (
    <div ref={rootRef} className={`relative w-full ${className}`} data-edify-date-picker="single">
      {name ? <input type="hidden" name={name} value={current} required={required} /> : null}
      <button
        id={fieldId}
        type="button"
        disabled={disabled}
        onClick={toggleOpen}
        aria-label={`${label}${displayValue ? `: ${displayValue}` : ''}`}
        aria-haspopup="dialog"
        aria-expanded={open}
        data-date-trigger="true"
        data-has-chevron="false"
        className={`group flex w-full cursor-pointer items-center gap-2.5 border text-left font-medium transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-[var(--brand-primary)]/40 disabled:cursor-not-allowed disabled:opacity-55 ${sizeClass} ${
          open
            ? 'border-[var(--brand-primary)] bg-white ring-2 ring-[var(--brand-primary)]/15'
            : 'border-[var(--edify-border)] bg-[var(--edify-card-surface)] hover:border-[var(--brand-primary)]/60 hover:bg-slate-50/70'
        }`}
      >
        <CalendarDays
          className="h-4 w-4 shrink-0 text-[var(--brand-primary)] transition-transform group-hover:scale-105"
          aria-hidden="true"
        />
        <span className={`min-w-0 flex-1 truncate ${displayValue ? 'text-[var(--edify-text)]' : 'text-[var(--edify-text-muted)]'}`}>
          {displayValue || placeholder}
        </span>
      </button>

      {open ? (
        <div
          role="dialog"
          aria-label={`${label} calendar`}
          data-date-popover="true"
          className={`absolute top-[calc(100%+6px)] z-50 w-[312px] max-w-[calc(100vw-24px)] rounded-[14px] border border-[var(--edify-border)] bg-white p-3.5 shadow-[0_14px_34px_-10px_rgba(15,23,42,0.22)] ${
            align === 'right' ? 'right-0' : 'left-0'
          }`}
        >
          {/* Calendar Header */}
          <div className="flex items-center justify-between gap-1">
            <button
              type="button"
              onClick={() => setView((v) => addMonths(v.y, v.m, pickingMonthYear ? -12 : -1))}
              aria-label={pickingMonthYear ? 'Previous year' : 'Previous month'}
              className="grid h-8 w-8 place-items-center rounded-[8px] text-slate-600 transition-colors hover:bg-slate-100 hover:text-slate-900"
            >
              <ChevronLeft className="h-4 w-4" aria-hidden="true" />
            </button>
            <button
              type="button"
              onClick={() => setPickingMonthYear((prev) => !prev)}
              aria-label="Choose month and year"
              className="rounded-[8px] px-2.5 py-1 text-[14px] font-bold text-[#0f172a] transition-colors hover:bg-blue-50 hover:text-[var(--brand-primary)]"
            >
              {pickingMonthYear ? String(view.y) : `${MONTHS_FULL[view.m - 1]} ${view.y}`}
            </button>
            <button
              type="button"
              onClick={() => setView((v) => addMonths(v.y, v.m, pickingMonthYear ? 12 : 1))}
              aria-label={pickingMonthYear ? 'Next year' : 'Next month'}
              className="grid h-8 w-8 place-items-center rounded-[8px] text-slate-600 transition-colors hover:bg-slate-100 hover:text-slate-900"
            >
              <ChevronRight className="h-4 w-4" aria-hidden="true" />
            </button>
          </div>

          {pickingMonthYear ? (
            <div className="mt-3 space-y-3">
              <div className="grid grid-cols-3 gap-1.5">
                {MONTHS_SHORT.map((mon, idx) => {
                  const active = idx + 1 === view.m;
                  return (
                    <button
                      key={mon}
                      type="button"
                      onClick={() => {
                        setView((v) => ({ y: v.y, m: idx + 1 }));
                        setPickingMonthYear(false);
                      }}
                      className={`h-9 rounded-[8px] text-[13px] font-semibold transition-colors ${
                        active
                          ? 'bg-[var(--brand-primary)] text-white'
                          : 'text-slate-700 hover:bg-slate-100'
                      }`}
                    >
                      {mon}
                    </button>
                  );
                })}
              </div>
              <div className="border-t border-slate-100 pt-2">
                <p className="mb-1.5 text-[11px] font-semibold uppercase tracking-wide text-slate-400">Year</p>
                <div className="grid grid-cols-4 gap-1">
                  {years.map((yr) => (
                    <button
                      key={yr}
                      type="button"
                      onClick={() => setView((v) => ({ y: yr, m: v.m }))}
                      className={`h-8 rounded-[7px] text-[12px] font-semibold ${
                        yr === view.y
                          ? 'bg-[#0f2942] text-white'
                          : 'text-slate-600 hover:bg-slate-100'
                      }`}
                    >
                      {yr}
                    </button>
                  ))}
                </div>
              </div>
            </div>
          ) : (
            <div className="mt-2.5" role="grid" aria-label={`${MONTHS_FULL[view.m - 1]} ${view.y}`} onKeyDown={handleGridKeyDown}>
              <div className="grid grid-cols-7 text-center" role="row">
                {WEEKDAYS_SHORT.map((d) => (
                  <span key={d} role="columnheader" className="py-1 text-[11px] font-semibold uppercase tracking-wide text-slate-400">
                    {d.slice(0, 2)}
                  </span>
                ))}
              </div>
              <div className="mt-0.5 grid grid-cols-7 gap-0.5">
                {grid.map((cell) => {
                  const avail = evaluateDayAvailability(cell.iso, effectivePolicy);
                  const isSelected = current === cell.iso;
                  const isToday = today === cell.iso;
                  const isFocused = focusedIso === cell.iso;
                  return (
                    <button
                      key={cell.iso}
                      type="button"
                      disabled={avail.disabled}
                      title={avail.reason || formatDisplayDate(cell.iso, 'weekday')}
                      aria-label={`${formatDisplayDate(cell.iso, 'weekday')}${avail.reason ? ` — ${avail.reason}` : ''}`}
                      aria-pressed={isSelected}
                      data-date-cell={cell.iso}
                      data-in-month={cell.inMonth ? 'true' : 'false'}
                      data-badge={avail.badge ?? ''}
                      onClick={() => commit(cell.iso)}
                      className={`relative grid h-9 w-9 place-items-center rounded-[9px] text-[13px] font-semibold transition-colors ${
                        isSelected
                          ? 'bg-[var(--brand-primary)] text-white shadow-sm'
                          : avail.disabled
                            ? 'cursor-not-allowed text-slate-300 line-through'
                            : cell.inMonth
                              ? 'text-slate-800 hover:bg-blue-50 hover:text-[var(--brand-primary)]'
                              : 'text-slate-400 hover:bg-slate-100'
                      } ${!isSelected && isToday ? 'ring-1.5 ring-[var(--brand-primary)] text-[var(--brand-primary)]' : ''} ${
                        isFocused && !isSelected ? 'outline outline-2 outline-[var(--brand-primary)]/40' : ''
                      }`}
                    >
                      <span>{cell.day}</span>
                      {avail.badge ? (
                        <span
                          aria-hidden="true"
                          className={`absolute bottom-1 h-1 w-1 rounded-full ${
                            avail.badge === 'holiday'
                              ? 'bg-amber-500'
                              : avail.badge === 'leave'
                                ? 'bg-rose-500'
                                : avail.badge === 'blackout'
                                  ? 'bg-slate-500'
                                  : 'bg-sky-500'
                          }`}
                        />
                      ) : null}
                    </button>
                  );
                })}
              </div>
            </div>
          )}

          {/* Footer: Quick Selections & FY / Policy Legend */}
          <div className="mt-3 flex flex-wrap items-center justify-between gap-2 border-t border-slate-100 pt-2.5 text-[12px]">
            {showQuickActions ? (
              <div className="flex items-center gap-1.5">
                {(() => {
                  const todayOk = !evaluateDayAvailability(today, effectivePolicy).disabled;
                  const tmrw = addDays(today, 1);
                  const tmrwOk = !evaluateDayAvailability(tmrw, effectivePolicy).disabled;
                  return (
                    <>
                      <button
                        type="button"
                        disabled={!todayOk}
                        onClick={() => commit(today)}
                        className="rounded-[7px] bg-blue-50 px-2.5 py-1 font-semibold text-[var(--brand-primary)] hover:bg-blue-100 disabled:opacity-40"
                      >
                        Today
                      </button>
                      <button
                        type="button"
                        disabled={!tmrwOk}
                        onClick={() => commit(tmrw)}
                        className="rounded-[7px] bg-slate-100 px-2.5 py-1 font-semibold text-slate-700 hover:bg-slate-200 disabled:opacity-40"
                      >
                        Tomorrow
                      </button>
                    </>
                  );
                })()}
              </div>
            ) : (
              <span />
            )}
            <div className="flex items-center gap-2">
              {showFiscalYear ? (
                <span className="rounded-full bg-slate-100 px-2 py-0.5 text-[11px] font-semibold text-slate-600" title={`${fyInfo.start} to ${fyInfo.end}`}>
                  {fyInfo.fy}
                </span>
              ) : null}
              {!required && current ? (
                <button
                  type="button"
                  onClick={() => commit('')}
                  className="font-semibold text-slate-500 hover:text-slate-800"
                >
                  Clear
                </button>
              ) : null}
            </div>
          </div>
          {effectivePolicy.mode === 'planning' ? (
            <p className="mt-2 text-[11px] text-slate-500">
              Sundays, public holidays &amp; approved leave are unavailable. Saturdays remain open.
            </p>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}

export interface EdifyDateRangePickerProps {
  startDate: string;
  endDate: string;
  onChange: (range: { startDate: string; endDate: string }) => void;
  label?: string;
  placeholder?: string;
  policy?: DatePolicy;
  showPresets?: boolean;
  align?: 'left' | 'right';
  className?: string;
}

/** Unified enterprise Date Range Picker with presets, range highlighting, and zero chevron. */
export function EdifyDateRangePicker({
  startDate,
  endDate,
  onChange,
  label = 'Date range',
  placeholder = 'Select date range',
  policy,
  showPresets = true,
  align = 'left',
  className = '',
}: EdifyDateRangePickerProps) {
  const today = useMemo(() => kampalaTodayIso(), []);
  const init = parseIso(startDate) ?? parseIso(today)!;
  const [open, setOpen] = useState(false);
  const [view, setView] = useState({ y: init.y, m: init.m });
  const [draftStart, setDraftStart] = useState(startDate);
  const [draftEnd, setDraftEnd] = useState(endDate);
  const rootRef = useRef<HTMLDivElement>(null);

  // A new range from the parent replaces the draft, during render so the
  // calendar never paints one frame of the old selection.
  const [shownRange, setShownRange] = useState({ startDate, endDate });
  if (shownRange.startDate !== startDate || shownRange.endDate !== endDate) {
    setShownRange({ startDate, endDate });
    setDraftStart(startDate);
    setDraftEnd(endDate);
  }

  useEffect(() => {
    if (!open) return undefined;
    const onPointer = (e: MouseEvent) => {
      if (!rootRef.current?.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setOpen(false);
    };
    document.addEventListener('mousedown', onPointer);
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('mousedown', onPointer);
      document.removeEventListener('keydown', onKey);
    };
  }, [open]);

  const grid = useMemo(() => buildMonthGrid(view.y, view.m), [view.y, view.m]);
  const presets = useMemo(() => rangePresets(today), [today]);

  const pickCell = (iso: string) => {
    if (evaluateDayAvailability(iso, policy).disabled) return;
    if (!draftStart || (draftStart && draftEnd)) {
      setDraftStart(iso);
      setDraftEnd('');
      return;
    }
    if (compareIso(iso, draftStart) < 0) {
      setDraftStart(iso);
      setDraftEnd(draftStart);
      onChange({ startDate: iso, endDate: draftStart });
      setOpen(false);
    } else {
      setDraftEnd(iso);
      onChange({ startDate: draftStart, endDate: iso });
      setOpen(false);
    }
  };

  const summary =
    startDate && endDate
      ? `${formatDisplayDate(startDate)} – ${formatDisplayDate(endDate)}`
      : startDate
        ? `${formatDisplayDate(startDate)} – …`
        : '';

  return (
    <div ref={rootRef} className={`relative w-full ${className}`} data-edify-date-picker="range">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-label={`${label}${summary ? `: ${summary}` : ''}`}
        aria-haspopup="dialog"
        aria-expanded={open}
        data-date-trigger="true"
        data-has-chevron="false"
        className={`flex h-10 w-full cursor-pointer items-center gap-2.5 rounded-[10px] border px-3.5 text-left text-[14px] font-medium transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-[var(--brand-primary)]/40 ${
          open
            ? 'border-[var(--brand-primary)] bg-white ring-2 ring-[var(--brand-primary)]/15'
            : 'border-[var(--edify-border)] bg-[var(--edify-card-surface)] hover:border-[var(--brand-primary)]/60 hover:bg-slate-50/70'
        }`}
      >
        <CalendarDays className="h-4 w-4 shrink-0 text-[var(--brand-primary)]" aria-hidden="true" />
        <span className={`min-w-0 flex-1 truncate ${summary ? 'text-[var(--edify-text)]' : 'text-[var(--edify-text-muted)]'}`}>
          {summary || placeholder}
        </span>
      </button>

      {open ? (
        <div
          role="dialog"
          aria-label={`${label} calendar`}
          data-date-popover="true"
          className={`absolute top-[calc(100%+6px)] z-50 flex flex-col gap-3 rounded-[14px] border border-[var(--edify-border)] bg-white p-3.5 shadow-[0_14px_34px_-10px_rgba(15,23,42,0.22)] sm:flex-row ${
            align === 'right' ? 'right-0' : 'left-0'
          }`}
        >
          {showPresets ? (
            <div className="flex flex-row flex-wrap gap-1 border-b border-slate-100 pb-2 sm:w-[130px] sm:flex-col sm:border-b-0 sm:border-r sm:pb-0 sm:pr-3">
              {presets.map((pr) => (
                <button
                  key={pr.id}
                  type="button"
                  onClick={() => {
                    onChange({ startDate: pr.start, endDate: pr.end });
                    setOpen(false);
                  }}
                  className="rounded-[8px] px-2.5 py-1.5 text-left text-[12px] font-semibold text-slate-700 hover:bg-blue-50 hover:text-[var(--brand-primary)]"
                >
                  {pr.label}
                </button>
              ))}
              <button
                type="button"
                onClick={() => {
                  setDraftStart('');
                  setDraftEnd('');
                  onChange({ startDate: '', endDate: '' });
                  setOpen(false);
                }}
                className="mt-auto rounded-[8px] px-2.5 py-1.5 text-left text-[12px] font-semibold text-slate-500 hover:bg-slate-100"
              >
                Clear Range
              </button>
            </div>
          ) : null}

          <div className="w-[280px]">
            <div className="flex items-center justify-between">
              <button
                type="button"
                onClick={() => setView((v) => addMonths(v.y, v.m, -1))}
                aria-label="Previous month"
                className="grid h-8 w-8 place-items-center rounded-[8px] text-slate-600 hover:bg-slate-100"
              >
                <ChevronLeft className="h-4 w-4" aria-hidden="true" />
              </button>
              <span className="text-[14px] font-bold text-[#0f172a]">
                {MONTHS_FULL[view.m - 1]} {view.y}
              </span>
              <button
                type="button"
                onClick={() => setView((v) => addMonths(v.y, v.m, 1))}
                aria-label="Next month"
                className="grid h-8 w-8 place-items-center rounded-[8px] text-slate-600 hover:bg-slate-100"
              >
                <ChevronRight className="h-4 w-4" aria-hidden="true" />
              </button>
            </div>
            <div className="mt-2 grid grid-cols-7 text-center">
              {WEEKDAYS_SHORT.map((d) => (
                <span key={d} className="py-1 text-[11px] font-semibold uppercase text-slate-400">
                  {d.slice(0, 2)}
                </span>
              ))}
            </div>
            <div className="grid grid-cols-7 gap-0.5">
              {grid.map((cell) => {
                const avail = evaluateDayAvailability(cell.iso, policy);
                const isStart = draftStart === cell.iso;
                const isEnd = draftEnd === cell.iso;
                const inRange =
                  Boolean(draftStart && draftEnd) &&
                  compareIso(cell.iso, draftStart) > 0 &&
                  compareIso(cell.iso, draftEnd) < 0;
                return (
                  <button
                    key={cell.iso}
                    type="button"
                    disabled={avail.disabled}
                    onClick={() => pickCell(cell.iso)}
                    className={`grid h-9 w-9 place-items-center rounded-[8px] text-[13px] font-semibold transition-colors ${
                      isStart || isEnd
                        ? 'bg-[var(--brand-primary)] text-white'
                        : inRange
                          ? 'bg-blue-100 text-[var(--brand-primary)]'
                          : avail.disabled
                            ? 'cursor-not-allowed text-slate-300 line-through'
                            : cell.inMonth
                              ? 'text-slate-800 hover:bg-blue-50'
                              : 'text-slate-400 hover:bg-slate-100'
                    }`}
                  >
                    {cell.day}
                  </button>
                );
              })}
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}
