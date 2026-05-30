"use client";

// MessageCenterLayout — the inbox surface.
//
// Responsive behaviour, by spec:
//   • desktop (lg+):    two-pane — list on the left, reader on the right
//   • tablet / mobile:  list-only; tapping a row navigates to the
//                       detail route (/{...}/messages/[id]) instead of
//                       opening a cramped in-place reader.
//
// The host page provides `detailHrefBase` (string prefix) so this
// component stays agnostic to where the detail page lives. We use a
// string base — not a function — because server components can't
// serialise functions across the server→client boundary.

import { useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import type { EdifyRole } from "@/lib/auth-public";
import type { Message } from "@/lib/messages-v2/types";
import { MessageList } from "./MessageList";
import { MessageReaderPane } from "./MessageReaderPane";

export function MessageCenterLayout({
  messages,
  role,
  detailHrefBase,
}: {
  messages:        Message[];
  role:            EdifyRole;
  /** Without trailing slash. `${base}/${id}` is the detail route. */
  detailHrefBase:  string;
}) {
  // Desktop-only state — the reader pane mirrors selection without
  // navigation. Mobile/tablet ignore this and link to detailHref(id).
  // Initial selection: honour `?id=<m.id>` query param so callers
  // (e.g. the MessageDrawer popover) can deep-link into a specific
  // thread on desktop; falls back to the first message.
  const search = useSearchParams();
  const initialId =
    (search?.get("id") && messages.some((m) => m.id === search.get("id"))
      ? (search.get("id") as string)
      : messages[0]?.id) ?? "";
  const [selectedId, setSelectedId] = useState<string>(initialId);

  // If the URL changes (back/forward, popover re-navigation) re-sync
  // the active selection.  We only update when the param actually maps
  // to a known message to avoid silently switching to an empty pane.
  useEffect(() => {
    const id = search?.get("id");
    if (id && id !== selectedId && messages.some((m) => m.id === id)) {
      setSelectedId(id);
    }
  }, [search, messages, selectedId]);

  const active = messages.find((m) => m.id === selectedId) ?? messages[0];

  return (
    <div className="grid grid-cols-12 gap-4 lg:gap-6 items-start">
      {/* List — full width on mobile/tablet, 5 cols on lg, 4 on xl */}
      <div className="col-span-12 lg:col-span-5 xl:col-span-4">
        {/* Mobile / tablet: rows are anchors → navigate to detail. */}
        <div className="lg:hidden">
          <MessageList messages={messages} detailHrefBase={detailHrefBase} />
        </div>
        {/* Desktop: rows select the active reader, no navigation. */}
        <div className="hidden lg:block">
          <MessageList
            messages={messages}
            selectedId={selectedId}
            onSelect={setSelectedId}
          />
        </div>
      </div>

      {/* Reader pane — desktop only. Mobile/tablet hide; the detail
          page is the reader. */}
      <div className="hidden lg:block col-span-12 lg:col-span-7 xl:col-span-8 sticky top-4">
        {active ? (
          <MessageReaderPane message={active} role={role} detailHref={`${detailHrefBase}/${active.id}`} />
        ) : (
          <div className="card rounded-2xl p-10 text-center text-body text-[var(--color-edify-muted)]">
            Select a message to read.
          </div>
        )}
      </div>
    </div>
  );
}
