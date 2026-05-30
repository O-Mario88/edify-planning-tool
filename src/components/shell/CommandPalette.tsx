"use client";

// CommandPalette — universal search + actions, ⌘K toggle.
//
// The single biggest power-user upgrade in this product. Once
// installed, users stop using the sidebar — they hit ⌘K, type a few
// letters, hit Enter. Stripe, Linear, Notion, GitHub, Figma, Vercel,
// Superhuman, Raycast all ship this; the absence of it is the loudest
// "this isn't a billion-dollar app yet" signal.
//
// Modes (auto-selected by query content):
//   • Pages    — every route in EXACT_ROUTE_TITLES, fuzzy-matched on
//                title and href, ranked by recency + prefix match.
//   • Actions  — global verbs that work from any page (Upload Resource,
//                Add Partner, Open Messages, …). Each action carries
//                its own href or click handler.
//   • Roles    — demo-only switch role helpers, surfaced when the
//                query starts with "role" / "switch" / "as".
//
// Keyboard contract:
//   ⌘K / Ctrl+K        — toggle open
//   Esc                — close
//   ↑ / ↓              — move selection
//   Enter              — fire selection (navigate or run handler)
//
// Mobile: the same palette is reachable via a magnifier icon in the
// dark MobileTopBar (added in a follow-up).

import { useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import {
  Search,
  ArrowRight,
  Hash,
  CornerDownLeft,
  ChevronUp,
  ChevronDown,
  Command as CommandIcon,
  Upload,
  Plus,
  MessageSquare,
  Bell,
  Settings,
  UserCog,
  X,
  type LucideIcon,
} from "lucide-react";
import { EXACT_ROUTE_TITLES, type RouteTitle } from "@/lib/route-titles";
import { cn } from "@/lib/utils";
import { fetchJson } from "@/lib/csrf-client";

// ────────── Item shape ──────────

type CmdSection = "Pages" | "Actions" | "Roles";

type CmdItem = {
  id:       string;
  section:  CmdSection;
  label:    string;
  detail?:  string;
  Icon:     LucideIcon;
  /** Either navigate (`href`) or run a custom handler. */
  href?:    string;
  onSelect?: (router: ReturnType<typeof useRouter>) => void;
  /** Keywords folded into the search index for fuzzier matching. */
  keywords?: string[];
};

// ────────── Static action + role registries ──────────

const ACTIONS: CmdItem[] = [
  { id: "act-msg",       section: "Actions", label: "Open Messages",     Icon: MessageSquare, href: "/messages",     keywords: ["chat", "inbox", "dm"] },
  { id: "act-notif",     section: "Actions", label: "Open Notifications", Icon: Bell,         href: "/notifications", keywords: ["alerts"] },
  { id: "act-add-partner", section: "Actions", label: "Add Partner",      Icon: Plus,         href: "/partners",      keywords: ["new partner", "create"] },
  { id: "act-upload-res", section: "Actions", label: "Upload Resource",   Icon: Upload,       href: "/resources",     keywords: ["file", "field guide", "policy"] },
  { id: "act-new-plan",   section: "Actions", label: "Create / Edit Plan", Icon: Plus,        href: "/plans/new",     keywords: ["new plan", "weekly plan"] },
  { id: "act-settings",   section: "Actions", label: "Open Settings",    Icon: Settings,     href: "/settings",      keywords: ["preferences", "account"] },
];

const ROLES: { email: string; name: string; role: string }[] = [
  { email: "paul.chinyama@edify.org",  name: "Paul Chinyama",  role: "CCEO"               },
  { email: "daniel.mwangi@edify.org",  name: "Daniel Mwangi",  role: "Country Program Lead" },
  { email: "sarah.okello@edify.org",   name: "Sarah Okello",   role: "Country Director"   },
  { email: "esther.wanjiru@edify.org", name: "Esther Wanjiru", role: "Regional VP"        },
  { email: "moses.tindi@edify.org",    name: "Moses Tindi",    role: "Program Accountant" },
  { email: "grace.alimo@edify.org",    name: "Grace Alimo",    role: "Impact Assessment"  },
  { email: "anne.wairimu@edify.org",   name: "Anne Wairimu",   role: "Human Resource"     },
  { email: "admin@edify.org",          name: "Edify Admin",    role: "Admin"              },
];

function buildRoleItems(): CmdItem[] {
  return ROLES.map((r) => ({
    id:      `role-${r.email}`,
    section: "Roles",
    label:   `Switch to ${r.role} (${r.name.split(" ")[0]})`,
    detail:  r.name,
    Icon:    UserCog,
    keywords: ["switch", "as", r.role.toLowerCase()],
    onSelect: async () => {
      await fetchJson("/api/demo/role-switch", { body: { email: r.email } });
      window.location.href = "/";
    },
  }));
}

function buildPageItems(): CmdItem[] {
  return Object.entries(EXACT_ROUTE_TITLES).map(([href, meta]: [string, RouteTitle]) => ({
    id:      `page-${href}`,
    section: "Pages",
    label:   meta.title,
    detail:  href,
    Icon:    Hash,
    href,
  }));
}

// ────────── Matching ──────────

function score(query: string, item: CmdItem): number {
  const q = query.toLowerCase().trim();
  if (!q) return 0;
  const hay = [item.label, item.detail, ...(item.keywords ?? [])]
    .filter(Boolean)
    .join(" ")
    .toLowerCase();
  if (hay.includes(q))               return 100 + (hay.startsWith(q) ? 50 : 0);
  // Fall-back: every query token must appear somewhere.
  const tokens = q.split(/\s+/);
  return tokens.every((t) => hay.includes(t)) ? 30 : 0;
}

// ────────── Component ──────────

export function CommandPalette() {
  const router = useRouter();
  const [open, setOpen]     = useState(false);
  const [query, setQuery]   = useState("");
  const [selected, setSelected] = useState(0);
  const inputRef = useRef<HTMLInputElement | null>(null);

  // ⌘K / Ctrl+K toggle, Esc to close. Listen at the document level so
  // the binding works regardless of focus.
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      const isToggle = (e.metaKey || e.ctrlKey) && (e.key === "k" || e.key === "K");
      if (isToggle) {
        e.preventDefault();
        setOpen((v) => !v);
        return;
      }
      if (e.key === "Escape" && open) {
        e.preventDefault();
        setOpen(false);
      }
    }
    document.addEventListener("keydown", onKey);
    // Also listen for a custom event so the magnifier icon in the
    // MobileTopBar can open the palette without prop-drilling state.
    function onOpen() { setOpen(true); }
    window.addEventListener("edify:open-command-palette", onOpen);
    return () => {
      document.removeEventListener("keydown", onKey);
      window.removeEventListener("edify:open-command-palette", onOpen);
    };
  }, [open]);

  // Focus the input when the palette opens; clear state when it closes.
  // Migrate the "clear on close" to a `key`-prop remount during the
  // React-19 sweep.
  useEffect(() => {
    if (open) {
      requestAnimationFrame(() => inputRef.current?.focus());
    } else {
      /* eslint-disable react-hooks/set-state-in-effect */
      setQuery("");
      setSelected(0);
      /* eslint-enable react-hooks/set-state-in-effect */
    }
  }, [open]);

  // Source of truth for items. Built once per render — small enough
  // that memoization isn't required, but kept lazy via useMemo for
  // readability.
  const items = useMemo<CmdItem[]>(() => {
    return [...buildPageItems(), ...ACTIONS, ...buildRoleItems()];
  }, []);

  const filtered = useMemo(() => {
    if (!query.trim()) {
      // Empty query: show a curated "jump to" list — top 5 pages + 5 actions.
      const pages = items.filter((i) => i.section === "Pages").slice(0, 5);
      const acts  = items.filter((i) => i.section === "Actions").slice(0, 5);
      return [...pages, ...acts];
    }
    return items
      .map((i) => ({ i, s: score(query, i) }))
      .filter((x) => x.s > 0)
      .sort((a, b) => b.s - a.s)
      .slice(0, 20)
      .map((x) => x.i);
  }, [items, query]);

  // Reset selection on query change so the first match stays highlighted.
  // Migrate to set-state-during-render with a "last query" sentinel during
  // the React-19 sweep.
  // eslint-disable-next-line react-hooks/set-state-in-effect
  useEffect(() => { setSelected(0); }, [query]);

  // Keyboard ↑↓ + Enter inside the palette.
  function onInputKey(e: React.KeyboardEvent<HTMLInputElement>) {
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setSelected((s) => Math.min(s + 1, filtered.length - 1));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setSelected((s) => Math.max(s - 1, 0));
    } else if (e.key === "Enter") {
      e.preventDefault();
      runItem(filtered[selected]);
    }
  }

  function runItem(item: CmdItem | undefined) {
    if (!item) return;
    setOpen(false);
    if (item.onSelect) {
      item.onSelect(router);
    } else if (item.href) {
      router.push(item.href);
    }
  }

  if (!open) return null;

  // Group items by section for the display.
  const groups = ["Pages", "Actions", "Roles"] as const;

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label="Command palette"
      className="fixed inset-0 z-[60] flex items-start justify-center px-4 pt-[10vh] sm:pt-[14vh] bg-black/50 backdrop-blur-sm"
      onClick={() => setOpen(false)}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        className="premium-modal w-full max-w-[640px] rounded-2xl text-[var(--text-primary)] shadow-[0_32px_96px_-24px_rgba(0,0,0,0.55)] overflow-hidden"
      >
        {/* Input */}
        <div className="flex items-center gap-3 px-4 py-3 border-b border-[var(--border-subtle)]">
          <Search size={16} className="text-[var(--text-muted)] shrink-0" />
          <input
            ref={inputRef}
            type="text"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={onInputKey}
            placeholder="Search pages, actions, roles…"
            className="flex-1 bg-transparent outline-none text-body-lg text-[var(--text-primary)] placeholder:text-[var(--text-muted)]"
          />
          <button
            type="button"
            onClick={() => setOpen(false)}
            aria-label="Close"
            className="grid place-items-center h-7 w-7 rounded-md text-[var(--text-muted)] hover:text-[var(--text-primary)] hover:bg-[var(--button-hover)]"
          >
            <X size={14} />
          </button>
        </div>

        {/* Results */}
        <div className="max-h-[60vh] overflow-y-auto py-2">
          {filtered.length === 0 && (
            <div className="px-5 py-8 text-center text-[13px] text-[var(--text-muted)]">
              No matches for <span className="font-semibold text-[var(--text-primary)]">&ldquo;{query}&rdquo;</span>
            </div>
          )}
          {groups.map((group) => {
            const rows = filtered.filter((i) => i.section === group);
            if (rows.length === 0) return null;
            return (
              <div key={group} className="px-1 mb-1">
                <div className="text-[10px] font-bold uppercase tracking-[0.08em] text-[var(--color-edify-muted)] px-4 pt-2 pb-1">
                  {group}
                </div>
                {rows.map((it) => {
                  const idx = filtered.indexOf(it);
                  const active = idx === selected;
                  const cls = cn(
                    "w-full flex items-center gap-3 px-4 py-2.5 rounded-lg text-left transition-colors",
                    active ? "bg-[var(--surface-selected)]" : "hover:bg-[var(--dropdown-hover)]",
                  );
                  const inner = (
                    <>
                      <span className="h-8 w-8 rounded-lg bg-[var(--color-edify-soft)] text-[var(--brand-primary)] grid place-items-center shrink-0">
                        <it.Icon size={14} />
                      </span>
                      <span className="min-w-0 flex-1">
                        <span className="block text-[13px] font-semibold text-[var(--text-primary)] truncate">
                          {it.label}
                        </span>
                        {it.detail && (
                          <span className="block text-[11px] text-[var(--text-muted)] truncate">
                            {it.detail}
                          </span>
                        )}
                      </span>
                      {active && (
                        <ArrowRight size={13} className="text-[var(--text-muted)] shrink-0" />
                      )}
                    </>
                  );
                  return it.href ? (
                    <Link
                      key={it.id}
                      href={it.href}
                      onClick={() => setOpen(false)}
                      onMouseEnter={() => setSelected(idx)}
                      className={cls}
                    >
                      {inner}
                    </Link>
                  ) : (
                    <button
                      key={it.id}
                      type="button"
                      onClick={() => runItem(it)}
                      onMouseEnter={() => setSelected(idx)}
                      className={cls}
                    >
                      {inner}
                    </button>
                  );
                })}
              </div>
            );
          })}
        </div>

        {/* Footer — keyboard hints */}
        <div className="flex items-center justify-between gap-3 px-4 py-2.5 border-t border-[var(--border-subtle)] bg-[var(--surface-2)] text-[11px] text-[var(--text-muted)]">
          <div className="flex items-center gap-3">
            <Hint Icon={ChevronUp}     label="up" />
            <Hint Icon={ChevronDown}   label="down" />
            <Hint Icon={CornerDownLeft} label="open" />
          </div>
          <div className="flex items-center gap-1.5">
            <kbd className="inline-flex items-center gap-1 px-1.5 h-5 rounded border border-[var(--border-card)] bg-[var(--surface-1)] text-[10px] font-semibold text-[var(--text-secondary)]">
              <CommandIcon size={9} /> K
            </kbd>
            <span>to toggle</span>
          </div>
        </div>
      </div>
    </div>
  );
}

function Hint({ Icon, label }: { Icon: LucideIcon; label: string }) {
  return (
    <span className="inline-flex items-center gap-1">
      <kbd className="grid place-items-center h-5 w-5 rounded border border-[var(--border-card)] bg-[var(--surface-1)] text-[var(--text-secondary)]">
        <Icon size={10} />
      </kbd>
      <span>{label}</span>
    </span>
  );
}
