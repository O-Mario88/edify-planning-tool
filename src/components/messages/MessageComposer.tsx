"use client";

import { useState, type FormEvent } from "react";
import { Paperclip, Send, Loader2 } from "lucide-react";
import { useDemoStore } from "@/components/demo/DemoStore";

// Demo-only message composer. Real backend would POST to a thread API.
// Here we just clear the input, show a toast, and let the visible thread
// scroll. The "Send" button is now a real form submit with feedback.
export function MessageComposer({ threadTitle }: { threadTitle: string }) {
  const { pushToast } = useDemoStore();
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);

  function onSubmit(e: FormEvent) {
    e.preventDefault();
    if (!draft.trim()) return;
    setBusy(true);
    window.setTimeout(() => {
      pushToast({
        tone: "success",
        title: "Message sent",
        body: `Delivered to ${threadTitle}.`,
      });
      setDraft("");
      setBusy(false);
    }, 350);
  }

  return (
    <form
      onSubmit={onSubmit}
      className="card rounded-2xl p-3 flex items-center gap-2 sticky bottom-3"
    >
      <button
        type="button"
        aria-label="Attach file"
        className="h-9 w-9 rounded-xl border border-[var(--color-edify-border)] grid place-items-center text-[var(--color-edify-muted)] hover:bg-[var(--color-edify-soft)]/40"
      >
        <Paperclip size={14} />
      </button>
      <input
        aria-label="Type a message"
        placeholder="Type a message…"
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
        disabled={busy}
        className="flex-1 h-9 px-3 rounded-xl border border-[var(--color-edify-border)] bg-white text-[13px] focus:outline-none focus:ring-2 focus:ring-[var(--color-edify-primary)]/30 disabled:opacity-55"
      />
      <button
        type="submit"
        disabled={busy || !draft.trim()}
        aria-label="Send message"
        className="h-9 px-3 rounded-xl bg-[var(--color-edify-primary)] text-white text-body font-semibold inline-flex items-center gap-1.5 hover:brightness-110 disabled:opacity-55"
      >
        {busy ? <Loader2 size={12} className="animate-spin" /> : <Send size={12} />}
        Send
      </button>
    </form>
  );
}
