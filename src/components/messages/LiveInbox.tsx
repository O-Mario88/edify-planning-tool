"use client";

// LiveInbox — the backend-wired inbox list. Fetches /api/messages (the same GET
// the bell badge + drawer use → returns { live, recent, counts }) and lists the
// caller's recent received messages, each linking to /messages/[threadId] (the
// LiveThread reader). One backend source of truth: the inbox, the bell drawer,
// and the reader all show the SAME live messages. Never fabricated — empty when
// the database has no inbox messages.
//
// Mirrors LiveCompose's fetch + DataStates contract. The recent records carry a
// threadId (BackendMessage.threadId), so each row routes by thread id — matching
// how /messages/[id] + the backend thread endpoint resolve.

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { ChevronRight } from "lucide-react";
import { EmptyState, ErrorState, LoadingState } from "@/components/ui/DataStates";
import type { BackendMessage } from "@/components/messages/messages-store";
import { cn } from "@/lib/utils";

function initialsOf(name: string): string {
  return (
    name
      .split(/\s+/)
      .map((n) => n[0])
      .filter(Boolean)
      .join("")
      .slice(0, 2)
      .toUpperCase() || "—"
  );
}

function formatStamp(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  return d.toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

export function LiveInbox() {
  const [recent, setRecent] = useState<BackendMessage[] | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    setErr(null);
    try {
      const res = await fetch("/api/messages", { credentials: "include" });
      const j = await res.json();
      if (j.live) setRecent((j.recent as BackendMessage[]) ?? []);
      else setErr(j.error || "Could not load your inbox.");
    } catch {
      setErr("Could not reach the server.");
    }
    setLoading(false);
  }, []);

  useEffect(() => {
    void load();
    // Live SSE events (new message / reply) re-pull the inbox, same as the bell.
    const onLive = () => void load();
    window.addEventListener("edify:realtime", onLive);
    return () => window.removeEventListener("edify:realtime", onLive);
  }, [load]);

  if (loading && !recent)
    return (
      <div className="card p-4">
        <LoadingState message="Loading your inbox…" />
      </div>
    );
  if (err)
    return (
      <div className="card p-4">
        <ErrorState message={err} onRetry={() => void load()} />
      </div>
    );
  if (!recent || recent.length === 0)
    return (
      <div className="card p-4">
        <EmptyState
          title="No messages"
          message="Feedback, decisions, debriefs, and coordination routed to you will appear here."
        />
      </div>
    );

  return (
    <div className="card overflow-hidden">
      <ul className="divide-y divide-[var(--color-edify-divider)]">
        {recent.map((m) => {
          const unread = m.status === "unread";
          const senderName = m.sender?.name ?? "Edify";
          const subject = m.thread?.subject ?? "(no subject)";
          const preview = (m.body ?? "").replace(/\s+/g, " ").trim();
          const threadId = m.threadId || m.id;
          return (
            <li key={m.id}>
              <Link
                href={`/messages/${threadId}`}
                className={cn(
                  "flex items-start gap-3 px-4 py-3 transition-colors relative",
                  unread
                    ? "bg-[var(--color-edify-soft)]/30 hover:bg-[var(--color-edify-soft)]/50"
                    : "hover:bg-[var(--surface-hover)]",
                )}
              >
                {unread && (
                  <span
                    aria-hidden
                    className="absolute left-0 top-3 bottom-3 w-[2.5px] rounded-r-full bg-[var(--color-edify-primary)]"
                  />
                )}
                <span className="h-9 w-9 rounded-full bg-[var(--color-edify-soft)] text-[var(--color-edify-primary)] grid place-items-center shrink-0 text-[11px] font-extrabold tabular">
                  {initialsOf(senderName)}
                </span>
                <div className="flex-1 min-w-0">
                  <div className="flex items-baseline justify-between gap-3">
                    <h4
                      className={cn(
                        "text-[13px] truncate leading-snug",
                        unread
                          ? "font-extrabold text-[var(--color-edify-text)]"
                          : "font-bold text-[var(--text-secondary)]",
                      )}
                    >
                      {subject}
                    </h4>
                    <time className="text-[10.5px] muted shrink-0 tabular">
                      {formatStamp(m.createdAt)}
                    </time>
                  </div>
                  <p className="text-[11px] muted leading-tight mt-0.5 truncate">
                    {senderName}
                  </p>
                  {preview && (
                    <p
                      className={cn(
                        "text-[11.5px] mt-0.5 leading-snug line-clamp-1",
                        unread ? "text-[var(--text-secondary)]" : "muted",
                      )}
                    >
                      {preview}
                    </p>
                  )}
                </div>
                <ChevronRight
                  size={15}
                  className="text-[var(--color-edify-muted)] shrink-0 mt-1"
                />
              </Link>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
