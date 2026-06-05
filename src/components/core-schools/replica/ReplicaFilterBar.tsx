"use client";

import { useEffect, useRef, useState } from "react";
import {
  Building2,
  CalendarRange,
  ChevronDown,
  Filter,
  GitCompareArrows,
  Globe2,
  Handshake,
  Layers,
  Lock,
  ShieldCheck,
  Sparkles,
  Trophy,
  Users,
  type LucideIcon,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { useFilterBar } from "@/hooks/use-filter-bar";
import { ExportButton } from "@/components/ui/ExportButton";
import { replicaBestPerforming, replicaAttention } from "@/lib/core-school-replica-mock";
import {
  ALL_SENTINEL,
  type FilterKey,
  type FilterOption,
  type FilterScope,
  type FilterScopeEntry,
} from "@/lib/filters/types";

// Core-schools export rows — best-performing + needs-attention, the two lists
// that make up the core-schools report.
const CORE_EXPORT_ROWS: Record<string, unknown>[] = [
  ...replicaBestPerforming.map((r) => ({ Category: "Best performing", ...(r as Record<string, unknown>) })),
  ...replicaAttention.map((r) => ({ Category: "Needs attention", ...(r as Record<string, unknown>) })),
];

// Filter bar — 10 dropdown pills on phones (sm-) become a single
// horizontal scroll strip with snap-to-pill; from md up they sit in a
// fixed grid; at xl they flatten to one row matching the reference.
//
// Every pill is now a controlled dropdown. State + URL sync lives in
// useFilterBar; the scope (which options each role can see) is passed
// in by the server-rendered page and never touched on the client.
//
// Invisible filters (per role visibility matrix) render nothing — the
// surrounding grid auto-flows so HR and RVP get a tighter bar without
// us hand-rolling a per-role layout.

type ChipEntry = {
  key:     FilterKey;
  icon:    LucideIcon;
  caption: string;
};

const CHIP_ORDER: ChipEntry[] = [
  { key: "fy",       icon: CalendarRange,    caption: "FY"              },
  { key: "quarter",  icon: GitCompareArrows, caption: "Quarter"         },
  { key: "region",   icon: Globe2,           caption: "Regions"         },
  { key: "district", icon: Building2,        caption: "Districts"       },
  { key: "cluster",  icon: Layers,           caption: "Clusters"        },
  { key: "cceo",     icon: Users,            caption: "CCEOs"           },
  { key: "partner",  icon: Handshake,        caption: "Partners"        },
  { key: "package",  icon: ShieldCheck,      caption: "Core Package"    },
  { key: "ssa",      icon: Sparkles,         caption: "SSA Status"      },
  { key: "champion", icon: Trophy,           caption: "Champion Status" },
];

export function ReplicaFilterBar({ scope }: { scope: FilterScope }) {
  const { selection, narrowedScope, setFilter, resetAll } = useFilterBar(scope);

  // Open state — one chip open at a time. `null` = nothing open.
  const [openKey, setOpenKey] = useState<FilterKey | null>(null);

  const visibleChips = CHIP_ORDER.filter((c) => narrowedScope[c.key].visible);

  return (
    <section className="px-3 sm:px-4 lg:px-6 py-3 space-y-2 md:space-y-0">
      {/* Mobile/sm-: horizontal scroll strip. */}
      <div className="md:hidden -mx-3 sm:-mx-4 px-3 sm:px-4 overflow-x-auto pb-1">
        <div className="inline-flex items-stretch gap-1.5 whitespace-nowrap">
          {visibleChips.map(({ key, icon, caption }) => (
            <FilterChip
              key={key}
              filterKey={key}
              icon={icon}
              caption={caption}
              entry={narrowedScope[key]}
              selectedId={selection[key]}
              isOpen={openKey === key}
              onToggle={() => setOpenKey(openKey === key ? null : key)}
              onClose={() => setOpenKey(null)}
              onSelect={(id) => {
                setFilter(key, id);
                setOpenKey(null);
              }}
              compact
            />
          ))}
        </div>
      </div>

      {/* md+: structured grid, fan out to one row at xl. */}
      <div className="hidden md:grid grid-cols-5 gap-1.5 lg:gap-2 xl:grid-cols-[repeat(10,minmax(0,1fr))_auto_auto]">
        {visibleChips.map(({ key, icon, caption }) => (
          <FilterChip
            key={key}
            filterKey={key}
            icon={icon}
            caption={caption}
            entry={narrowedScope[key]}
            selectedId={selection[key]}
            isOpen={openKey === key}
            onToggle={() => setOpenKey(openKey === key ? null : key)}
            onClose={() => setOpenKey(null)}
            onSelect={(id) => {
              setFilter(key, id);
              setOpenKey(null);
            }}
          />
        ))}

        <button
          type="button"
          onClick={resetAll}
          className="hidden xl:inline-flex items-center justify-center gap-1.5 h-11 px-3 rounded-xl bg-white border border-[var(--color-edify-border)] hover:bg-slate-50 text-body font-semibold text-slate-700 transition-colors"
          title="Reset all filters to defaults"
        >
          <Filter size={13} />
          Filters
        </button>
        <ExportButton
          rows={CORE_EXPORT_ROWS}
          filename="core-schools-report"
          label="Export Report"
          className="hidden xl:inline-flex !h-11 !px-4 !rounded-xl !bg-emerald-500 !text-white !border-transparent !font-extrabold hover:!opacity-95 shadow-[0_8px_24px_-10px_rgba(16,185,129,0.55)]"
        />
      </div>

      {/* Filters + Export — below the strip on phones, below the grid
          on md/lg, inline at xl (rendered above already). */}
      <div className="flex items-stretch gap-1.5 md:gap-2 xl:hidden">
        <button
          type="button"
          onClick={resetAll}
          className="inline-flex items-center justify-center gap-1.5 h-10 sm:h-11 px-3 rounded-xl bg-white border border-[var(--color-edify-border)] hover:bg-slate-50 text-body font-semibold text-slate-700 transition-colors flex-1 sm:flex-none"
        >
          <Filter size={13} />
          Filters
        </button>
        <ExportButton
          rows={CORE_EXPORT_ROWS}
          filename="core-schools-report"
          label="Export Report"
          className="!h-10 sm:!h-11 !px-4 !rounded-xl !bg-emerald-500 !text-white !border-transparent !font-extrabold hover:!opacity-95 flex-1 sm:flex-none shadow-[0_8px_24px_-10px_rgba(16,185,129,0.55)]"
        />
      </div>
    </section>
  );
}

// ────────── FilterChip ──────────

function FilterChip({
  filterKey,
  icon: Icon,
  caption,
  entry,
  selectedId,
  isOpen,
  onToggle,
  onClose,
  onSelect,
  compact,
}: {
  filterKey:  FilterKey;
  icon:       LucideIcon;
  caption:    string;
  entry:      FilterScopeEntry;
  selectedId: string;
  isOpen:     boolean;
  onToggle:   () => void;
  onClose:    () => void;
  onSelect:   (id: string) => void;
  /** When true: fixed-width pill for the mobile scroll strip. */
  compact?:   boolean;
}) {
  const selected =
    entry.options.find((o) => o.id === selectedId) ?? entry.options[0];
  const label    = selected?.label   ?? "—";
  const subLabel = selected?.caption;

  // Disabled when the entry is gated for this role (e.g. RVP partner).
  const disabled = !!entry.disabledReason;

  // Empty when the user's scope produces no real options (just the
  // "All …" sentinel). Still openable — the menu shows the empty
  // state so the user understands why.
  const isEmpty = entry.options.length <= 1;

  return (
    <div className={cn("relative", compact && "shrink-0")}>
      <button
        type="button"
        aria-haspopup="listbox"
        aria-expanded={isOpen}
        disabled={disabled}
        onClick={onToggle}
        className={cn(
          "h-11 px-2.5 rounded-xl bg-white border inline-flex items-center gap-1.5 text-left transition-colors min-w-0 w-full",
          "border-[var(--color-edify-border)] hover:bg-slate-50 active:bg-slate-100",
          isOpen && "ring-2 ring-emerald-500/40 border-emerald-400",
          disabled && "opacity-60 cursor-not-allowed hover:bg-white",
          compact && "min-w-[140px]",
        )}
        title={entry.disabledReason}
      >
        {disabled ? (
          <Lock size={13} className="text-slate-400 shrink-0" />
        ) : (
          <Icon size={13} className="text-slate-400 shrink-0" />
        )}
        <span className="flex flex-col items-start leading-tight min-w-0 flex-1">
          <span className="text-[9px] uppercase tracking-[0.08em] muted font-bold truncate w-full">
            {caption}
          </span>
          <span className="text-[11.5px] font-semibold text-slate-800 truncate w-full">
            {label}
          </span>
          {subLabel && (
            <span className="text-[9.5px] muted truncate w-full">{subLabel}</span>
          )}
        </span>
        <ChevronDown
          size={12}
          className={cn(
            "text-slate-400 shrink-0 transition-transform",
            isOpen && "rotate-180",
          )}
        />
      </button>

      {isOpen && (
        <FilterMenu
          options={entry.options}
          selectedId={selectedId}
          onSelect={onSelect}
          onClose={onClose}
          emptyState={emptyStateFor(filterKey, isEmpty)}
        />
      )}
    </div>
  );
}

// ────────── FilterMenu ──────────

function FilterMenu({
  options,
  selectedId,
  onSelect,
  onClose,
  emptyState,
}: {
  options:    FilterOption[];
  selectedId: string;
  onSelect:   (id: string) => void;
  onClose:    () => void;
  emptyState: string | null;
}) {
  const ref = useRef<HTMLDivElement>(null);

  // Outside click + Escape.
  useEffect(() => {
    function onDown(e: MouseEvent) {
      if (!ref.current?.contains(e.target as Node)) onClose();
    }
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") onClose();
    }
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [onClose]);

  return (
    <div
      ref={ref}
      role="listbox"
      className="premium-popover absolute z-30 top-full mt-1 left-0 min-w-[220px] max-w-[320px] max-h-[280px] overflow-auto py-1"
    >
      {emptyState ? (
        <div className="px-3 py-3 text-[12px] muted">{emptyState}</div>
      ) : (
        options.map((o) => (
          <button
            key={o.id}
            type="button"
            role="option"
            aria-selected={o.id === selectedId}
            onClick={() => onSelect(o.id)}
            className={cn(
              "w-full flex flex-col items-start text-left px-3 py-2 hover:bg-slate-50 transition-colors",
              o.id === selectedId && "bg-emerald-50/60",
            )}
          >
            <span className="text-[12px] font-semibold text-slate-800 truncate w-full">
              {o.label}
            </span>
            {o.caption && (
              <span className="text-[10.5px] muted truncate w-full">{o.caption}</span>
            )}
          </button>
        ))
      )}
    </div>
  );
}

// ────────── Empty state copy ──────────
//
// Only shown when the user's scope produces no real options. The
// "All …" sentinel is always present, so we treat "options.length ≤ 1"
// as empty. Each filter gets its own copy per spec §16.
function emptyStateFor(key: FilterKey, isEmpty: boolean): string | null {
  if (!isEmpty) return null;
  switch (key) {
    case "region":   return "No regions available for your scope.";
    case "district": return "No districts available for the selected region.";
    case "cluster":  return "No clusters found for selected filters.";
    case "cceo":     return "No CCEOs found for selected filters.";
    case "partner":  return "No partners found for this area.";
    default:         return null;
  }
}

// Re-export the sentinel for any callers that need to compare against
// the "All …" state without importing from lib/filters.
export { ALL_SENTINEL };
