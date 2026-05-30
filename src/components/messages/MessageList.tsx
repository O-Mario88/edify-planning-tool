"use client";

// MessageList — the inbox panel.
//
// Renders the header (title + unread count + segmented filter toggle),
// the search input, and the list. Selection is opaque: the host
// controls it (so the desktop layout can use it for a 2-pane reader,
// while mobile/tablet ignores it and passes `linkTo` so rows navigate).

import { useMemo } from "react";
import { Inbox, Search } from "lucide-react";
import { applyListFilter, applySearch, type ListFilterKey } from "@/lib/messages-v2/access";
import type { Message } from "@/lib/messages-v2/types";
import { cn } from "@/lib/utils";
import { MessageListItem } from "./MessageListItem";
import { MessageEmptyState } from "./MessageEmptyState";
import { useUrlSearch, useUrlState } from "@/hooks/use-url-state";

const QUICK_FILTERS: { key: ListFilterKey; label: string }[] = [
  { key: "all",             label: "All"      },
  { key: "unread",          label: "Unread"   },
  { key: "action_required", label: "Action"   },
  { key: "urgent",          label: "Urgent"   },
];
const FILTER_KEYS = QUICK_FILTERS.map((f) => f.key) as readonly ListFilterKey[];

export function MessageList({
  messages,
  selectedId,
  onSelect,
  /** When set, each row links to `${detailHrefBase}/${id}` instead of
   *  calling onSelect. Used by mobile/tablet to navigate to the detail
   *  page. String-only — avoids passing a function across the client
   *  boundary, which Next.js doesn't allow with server-component hosts. */
  detailHrefBase,
  /** Hide the search bar (e.g. when the host page already provides one). */
  hideSearch = false,
}: {
  messages:        Message[];
  selectedId?:     string;
  onSelect?:       (id: string) => void;
  detailHrefBase?: string;
  hideSearch?:     boolean;
}) {
  // Filter is URL-backed so an inbox view can be shared / deep-linked
  // from a notification ("Action items in Uganda" → ?filter=action_required).
  const [filter, setFilter] = useUrlState<ListFilterKey>({
    key: "filter",
    defaultValue: "all",
    allowed: FILTER_KEYS,
  });
  // Search is debounced (300ms) — input stays at native speed, URL
  // only writes the trailing value so a noisy keystream isn't a noisy
  // history.
  const [query, setQuery] = useUrlSearch({ key: "q" });

  const visible = useMemo(() => {
    return applySearch(applyListFilter(messages, filter), query);
  }, [messages, filter, query]);

  const unreadCount = messages.filter((m) => m.status === "unread" || m.status === "action_required").length;

  return (
    <section className="card rounded-2xl p-0 overflow-hidden flex flex-col">
      <header className="px-4 pt-4 pb-3 flex items-center justify-between gap-3">
        <div className="flex items-baseline gap-2 min-w-0">
          <h3 className="text-[15px] font-extrabold tracking-tight inline-flex items-center gap-2">
            <Inbox size={14} className="text-[var(--color-edify-muted)]" />
            Inbox
          </h3>
          {unreadCount > 0 && (
            <span className="text-[11.5px] text-[var(--color-edify-muted)] tabular">{unreadCount} unread</span>
          )}
        </div>
        <div className="inline-flex items-center rounded-md bg-[var(--color-edify-soft)]/60 p-0.5">
          {QUICK_FILTERS.map((f) => {
            const isActive = filter === f.key;
            return (
              <button
                key={f.key}
                type="button"
                onClick={() => setFilter(f.key)}
                className={cn(
                  "h-7 px-2.5 rounded-[5px] text-[11px] font-semibold transition-colors",
                  isActive
                    ? "bg-white text-[var(--color-edify-text)] shadow-[0_1px_2px_rgba(15,23,32,0.06)]"
                    : "text-[var(--color-edify-muted)] hover:text-[var(--color-edify-text)]",
                )}
              >
                {f.label}
              </button>
            );
          })}
        </div>
      </header>

      {!hideSearch && (
        <div className="px-4 pb-3">
          <div className="relative">
            <Search size={13} className="absolute left-3 top-1/2 -translate-y-1/2 text-[var(--color-edify-muted)] pointer-events-none" />
            <input
              type="search"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Search sender, school, cluster, partner…"
              aria-label="Search messages"
              className="h-9 w-full pl-9 pr-3 rounded-lg border border-[var(--color-edify-border)] bg-[var(--color-card)] text-[12px] placeholder:text-[var(--color-edify-muted)] focus:outline-none focus:ring-2 focus:ring-[var(--color-edify-primary)]/30"
            />
          </div>
        </div>
      )}

      <ul className="flex-1 overflow-y-auto">
        {visible.length === 0 ? (
          <MessageEmptyState filter={filter} hasQuery={query.length > 0} />
        ) : (
          visible.map((m) => (
            <MessageListItem
              key={m.id}
              message={m}
              selected={selectedId === m.id}
              onClick={onSelect ? () => onSelect(m.id) : undefined}
              href={detailHrefBase ? `${detailHrefBase}/${m.id}` : undefined}
            />
          ))
        )}
      </ul>
    </section>
  );
}
