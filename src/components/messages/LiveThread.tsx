"use client";

// LiveThread — the backend-wired thread reader. Fetches the full thread from
// /api/messages/thread/[id] (participant-scoped; the backend marks the caller's
// own messages read on read) and renders every message in order, then a reply
// box that POSTs /api/messages/[id]/reply. The [id] route param is a THREAD id
// (the backend resolves both thread + reply by thread id), so the same id drives
// both fetches. Mirrors LiveCompose's fetch + csrf + DataStates contract.
//
// Replaces the mock MessageDetailPage on /messages/[id]. Shows the SAME live
// messages the bell drawer + live inbox surface — one backend source of truth.

import { useCallback, useEffect, useRef, useState } from "react";
import { Send, Loader2 } from "lucide-react";
import { EmptyState, ErrorState, LoadingState } from "@/components/ui/DataStates";
import { csrfHeaders } from "@/lib/csrf-client";
import { cn } from "@/lib/utils";

type ThreadMessage = {
  id: string;
  body: string;
  senderId: string;
  senderName: string;
  mine: boolean;
  createdAt: string;
};

type ThreadVM = {
  id: string;
  subject: string;
  contextType: string | null;
  contextId: string | null;
  messages: ThreadMessage[];
};

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

export function LiveThread({ threadId }: { threadId: string }) {
  const [thread, setThread] = useState<ThreadVM | null>(null);
  const [loadErr, setLoadErr] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const [reply, setReply] = useState("");
  const [busy, setBusy] = useState(false);
  const [sendErr, setSendErr] = useState<string | null>(null);

  const endRef = useRef<HTMLDivElement | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setLoadErr(null);
    try {
      const res = await fetch(
        `/api/messages/thread/${encodeURIComponent(threadId)}`,
        { credentials: "include" },
      );
      const j = await res.json();
      if (j.live && j.thread) setThread(j.thread as ThreadVM);
      else setLoadErr(j.error || "Could not load this conversation.");
    } catch {
      setLoadErr("Could not reach the server.");
    }
    setLoading(false);
  }, [threadId]);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    endRef.current?.scrollIntoView({ block: "end" });
  }, [thread?.messages.length]);

  const canSend = reply.trim().length > 0 && !busy;

  const send = async () => {
    if (!canSend) return;
    setBusy(true);
    setSendErr(null);
    try {
      const res = await fetch(
        `/api/messages/${encodeURIComponent(threadId)}/reply`,
        {
          method: "POST",
          credentials: "include",
          headers: { "Content-Type": "application/json", ...csrfHeaders() },
          body: JSON.stringify({ body: reply.trim() }),
        },
      );
      const j = await res.json();
      if (j.live) {
        setReply("");
        await load(); // re-pull so the new reply (and read-state) is canonical
      } else {
        setSendErr(j.error || "The reply was rejected.");
      }
    } catch {
      setSendErr("Could not reach the server.");
    }
    setBusy(false);
  };

  if (loading && !thread)
    return (
      <div className="px-4 sm:px-5 lg:px-6 pt-2 pb-12 max-w-[820px]">
        <LoadingState message="Loading conversation…" />
      </div>
    );
  if (loadErr)
    return (
      <div className="px-4 sm:px-5 lg:px-6 pt-2 pb-12 max-w-[820px]">
        <ErrorState message={loadErr} onRetry={() => void load()} />
      </div>
    );
  if (!thread)
    return (
      <div className="px-4 sm:px-5 lg:px-6 pt-2 pb-12 max-w-[820px]">
        <EmptyState title="Conversation not found" message="This thread is no longer available." />
      </div>
    );

  return (
    <div className="px-4 sm:px-5 lg:px-6 pt-2 pb-12 max-w-[820px] space-y-4">
      <div className="card p-4 sm:p-5 space-y-4">
        <header>
          <h2 className="text-[15px] font-extrabold tracking-tight text-[var(--color-edify-text)]">
            {thread.subject || "(no subject)"}
          </h2>
          {thread.contextType && (
            <p className="text-[11px] muted mt-0.5 capitalize">
              {thread.contextType.replace(/_/g, " ")}
            </p>
          )}
        </header>

        {thread.messages.length === 0 ? (
          <EmptyState title="No messages" message="This conversation has no messages yet." />
        ) : (
          <ul className="space-y-3">
            {thread.messages.map((m) => (
              <li
                key={m.id}
                className={cn(
                  "flex items-start gap-2.5",
                  m.mine && "flex-row-reverse",
                )}
              >
                <span className="h-8 w-8 rounded-full bg-[var(--color-edify-soft)] text-[var(--color-edify-primary)] grid place-items-center shrink-0 text-[10px] font-extrabold tabular">
                  {initialsOf(m.senderName)}
                </span>
                <div
                  className={cn(
                    "flex-1 min-w-0 max-w-[80%] rounded-2xl px-3.5 py-2.5",
                    m.mine
                      ? "bg-[var(--color-edify-primary)] text-white"
                      : "bg-[var(--color-edify-soft)]/50 text-[var(--color-edify-text)]",
                  )}
                >
                  <div className="flex items-baseline justify-between gap-3">
                    <span
                      className={cn(
                        "text-[11.5px] font-bold truncate",
                        m.mine ? "text-white/90" : "text-[var(--color-edify-text)]",
                      )}
                    >
                      {m.mine ? "You" : m.senderName}
                    </span>
                    <time
                      className={cn(
                        "text-[10px] shrink-0 tabular",
                        m.mine ? "text-white/70" : "muted",
                      )}
                    >
                      {formatStamp(m.createdAt)}
                    </time>
                  </div>
                  <p className="text-[12.5px] leading-snug mt-1 whitespace-pre-wrap break-words">
                    {m.body}
                  </p>
                </div>
              </li>
            ))}
          </ul>
        )}
        <div ref={endRef} />
      </div>

      {/* Reply box */}
      <div className="card p-4 space-y-3">
        <label className="block">
          <span className="block text-[10.5px] font-bold uppercase tracking-wide muted mb-1">
            Reply
          </span>
          <textarea
            value={reply}
            onChange={(e) => setReply(e.target.value)}
            rows={3}
            placeholder="Write a reply…"
            className="w-full px-2.5 py-2 rounded-lg border border-[var(--color-edify-border)] bg-[var(--surface-1)] text-[13px] resize-y"
          />
        </label>
        {sendErr && (
          <p className="text-[12px] text-rose-600 font-semibold">{sendErr}</p>
        )}
        <div className="flex items-center justify-end">
          <button
            disabled={!canSend}
            onClick={send}
            className="h-10 px-5 inline-flex items-center gap-1.5 rounded-lg bg-[var(--color-edify-primary)] hover:bg-[var(--color-edify-dark)] text-white text-[12.5px] font-bold disabled:opacity-50"
          >
            {busy ? (
              <>
                <Loader2 size={15} className="animate-spin" /> Sending
              </>
            ) : (
              <>
                <Send size={15} /> Send reply
              </>
            )}
          </button>
        </div>
      </div>
    </div>
  );
}
