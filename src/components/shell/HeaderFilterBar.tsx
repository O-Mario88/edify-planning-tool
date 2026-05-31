"use client";

// HeaderFilterBar — the ONE live, role-scoped, URL-synced filter bar for
// page headers. Replaces the decorative read-only pills that used to
// render from static mock labels. It drives the existing filter engine:
//   getFilterScope({user})  → role-aware options (computed server-side)
//   useFilterBar(scope)     → selection + cascade + URL persistence
// Every change writes to the URL query string (?fy=…&region=…), so the
// view is shareable and any card that reads useActiveFilters() updates.

import { useEffect, useRef, useState } from "react";
import {
  Calendar, CalendarRange, MapPin, Building2, Users, UserCog, Handshake,
  Package, ShieldCheck, Trophy, ChevronDown, Check, Lock, type LucideIcon,
} from "lucide-react";
import { useFilterBar } from "@/hooks/use-filter-bar";
import {
  type FilterKey,
  type FilterScope,
  type FilterScopeEntry,
  type FilterOption,
} from "@/lib/filters/types";
import { cn } from "@/lib/utils";

const META: Record<FilterKey, { icon: LucideIcon; caption: string }> = {
  fy:       { icon: Calendar,      caption: "Financial Year" },
  quarter:  { icon: CalendarRange, caption: "Quarter" },
  region:   { icon: MapPin,        caption: "Region" },
  district: { icon: Building2,     caption: "District" },
  cluster:  { icon: Users,         caption: "Cluster" },
  cceo:     { icon: UserCog,       caption: "CCEO" },
  partner:  { icon: Handshake,     caption: "Partner" },
  package:  { icon: Package,       caption: "Core Package" },
  ssa:      { icon: ShieldCheck,   caption: "SSA Status" },
  champion: { icon: Trophy,        caption: "Champion" },
};

// Header display order. Role visibility (from the scope) filters this
// down further — HR never sees Partner, etc.
const ORDER: FilterKey[] = [
  "fy", "quarter", "region", "district", "cluster", "cceo", "partner",
  "package", "ssa", "champion",
];

export function HeaderFilterBar({ scope }: { scope: FilterScope }) {
  const { selection, narrowedScope, setFilter } = useFilterBar(scope);
  const [openKey, setOpenKey] = useState<FilterKey | null>(null);

  const keys = ORDER.filter((k) => narrowedScope[k].visible);

  return (
    <div className="flex items-center gap-2 flex-wrap min-w-0" role="group" aria-label="Filters">
      {keys.map((k) => (
        <FilterChip
          key={k}
          filterKey={k}
          entry={narrowedScope[k]}
          selectedId={selection[k]}
          isOpen={openKey === k}
          onToggle={() => setOpenKey((o) => (o === k ? null : k))}
          onClose={() => setOpenKey(null)}
          onSelect={(id) => {
            setFilter(k, id);
            setOpenKey(null);
          }}
        />
      ))}
    </div>
  );
}

function FilterChip({
  filterKey, entry, selectedId, isOpen, onToggle, onClose, onSelect,
}: {
  filterKey: FilterKey;
  entry: FilterScopeEntry;
  selectedId: string;
  isOpen: boolean;
  onToggle: () => void;
  onClose: () => void;
  onSelect: (id: string) => void;
}) {
  const { icon: Icon, caption } = META[filterKey];
  const selected = entry.options.find((o) => o.id === selectedId) ?? entry.options[0];
  const label = selected?.label ?? "—";
  const disabled = !!entry.disabledReason;
  const ref = useRef<HTMLDivElement | null>(null);

  // Outside-click + Esc close for the open menu.
  useEffect(() => {
    if (!isOpen) return;
    function onDoc(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) onClose();
    }
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") onClose();
    }
    document.addEventListener("mousedown", onDoc);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDoc);
      document.removeEventListener("keydown", onKey);
    };
  }, [isOpen, onClose]);

  return (
    <div ref={ref} className="relative">
      <button
        type="button"
        aria-haspopup="listbox"
        aria-expanded={isOpen}
        disabled={disabled}
        title={entry.disabledReason}
        onClick={onToggle}
        className={cn(
          "h-10 px-3 rounded-xl border inline-flex items-center gap-1.5 transition-colors",
          "bg-[var(--color-card)] border-[var(--color-edify-border)] text-[var(--color-edify-text)]",
          "hover:bg-[var(--color-edify-soft)]/40",
          "shadow-[0_1px_2px_rgba(15,23,32,0.04)]",
          isOpen && "ring-2 ring-[var(--color-edify-primary)]/35 border-[var(--color-edify-primary)]/50",
          disabled && "opacity-55 cursor-not-allowed hover:bg-[var(--color-card)]",
        )}
      >
        {disabled ? (
          <Lock size={13} className="text-[var(--color-edify-muted)] shrink-0" />
        ) : (
          <Icon size={13} className="text-[var(--color-edify-muted)] shrink-0" />
        )}
        <span className="text-body font-semibold truncate max-w-[150px]">{label}</span>
        <ChevronDown
          size={13}
          className={cn("text-[var(--color-edify-muted)] shrink-0 transition-transform", isOpen && "rotate-180")}
        />
      </button>

      {isOpen && !disabled && (
        <FilterMenu
          caption={caption}
          options={entry.options}
          selectedId={selectedId}
          onSelect={onSelect}
        />
      )}
    </div>
  );
}

function FilterMenu({
  caption, options, selectedId, onSelect,
}: {
  caption: string;
  options: FilterOption[];
  selectedId: string;
  onSelect: (id: string) => void;
}) {
  return (
    <div
      role="listbox"
      aria-label={caption}
      className={cn(
        "absolute left-0 top-[calc(100%+6px)] z-50 w-[240px] max-w-[80vw]",
        "premium-popover rounded-xl overflow-hidden",
        "shadow-[0_20px_56px_-12px_rgba(15,23,32,0.30),0_4px_10px_rgba(15,23,32,0.10)]",
        "flex flex-col",
      )}
      style={{ maxHeight: "min(340px, 60vh)" }}
    >
      <div className="px-3 py-2 border-b border-[var(--color-edify-border)] text-[10px] font-bold uppercase tracking-[0.08em] text-[var(--color-edify-muted)]">
        {caption}
      </div>
      <ul className="flex-1 min-h-0 overflow-y-auto py-1">
        {options.length <= 1 && options[0] ? (
          <li>
            <MenuRow option={options[0]} selected onClick={() => onSelect(options[0].id)} />
          </li>
        ) : (
          options.map((o) => (
            <li key={o.id}>
              <MenuRow option={o} selected={o.id === selectedId} onClick={() => onSelect(o.id)} />
            </li>
          ))
        )}
      </ul>
    </div>
  );
}

function MenuRow({
  option, selected, onClick,
}: {
  option: FilterOption;
  selected: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      role="option"
      aria-selected={selected}
      onClick={onClick}
      className={cn(
        "w-full text-left px-3 py-2 flex items-center gap-2 transition-colors",
        selected
          ? "bg-[var(--color-edify-soft)]/60"
          : "hover:bg-[var(--color-edify-soft)]/40",
      )}
    >
      <span className="flex-1 min-w-0">
        <span className="block text-body font-semibold text-[var(--color-edify-text)] truncate">
          {option.label}
        </span>
        {option.caption && (
          <span className="block text-[10.5px] text-[var(--color-edify-muted)] truncate">
            {option.caption}
          </span>
        )}
      </span>
      {selected && <Check size={13} className="text-[var(--color-edify-primary)] shrink-0" />}
    </button>
  );
}
