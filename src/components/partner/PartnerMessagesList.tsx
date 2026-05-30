"use client";

// PartnerMessagesList — inbox-style message list. Calm, scannable.
// Each row: sender + role chip, subject (first line), preview, date,
// unread dot. Right-rail shows the selected message body — but only
// stub content; the actual messaging engine is out of scope.

import { useState } from "react";
import { CornerUpLeft } from "lucide-react";
import { cn } from "@/lib/utils";

type MessageKind = "feedback" | "correction" | "reminder" | "coordination";

type Message = {
  id: string;
  sender: string;
  senderRole: "CCEO" | "Program Lead" | "M&E" | "Accountant";
  kind: MessageKind;
  subject: string;
  preview: string;
  body: string;
  sentAt: string;
  unread: boolean;
};

// Kind colour now drives a single thin accent stripe on the list row
// rather than a heavyweight pill — keeps the inbox calm. Reader still
// shows a small label so a partner knows *what kind* of note arrived.
const KIND_ACCENT: Record<MessageKind, { stripe: string; label: string; dot: string }> = {
  feedback:     { stripe: "before:bg-blue-400/70",    label: "Feedback",     dot: "bg-blue-500"    },
  correction:   { stripe: "before:bg-amber-400/80",   label: "Correction",   dot: "bg-amber-500"   },
  reminder:     { stripe: "before:bg-violet-400/70",  label: "Reminder",     dot: "bg-violet-500"  },
  coordination: { stripe: "before:bg-emerald-400/70", label: "Coordination", dot: "bg-emerald-500" },
};

const MESSAGES: Message[] = [
  {
    id: "M-1",
    sender: "Sarah Nanyongo",
    senderRole: "CCEO",
    kind: "correction",
    subject: "Kireka debrief — attendance sheet unclear",
    preview: "Hi Daniel, the attendance sheet you uploaded for the Kireka training debrief is missing teacher names...",
    body:
      "Hi Daniel,\n\nThe attendance sheet you uploaded for the Kireka training debrief is missing teacher names — please re-upload with names, school, date, and facilitator visible. I've returned the activity in your Corrections queue, due Sat May 16.\n\nThanks,\nSarah",
    sentAt: "Today · 9:34 AM",
    unread: true,
  },
  {
    id: "M-2",
    sender: "Daniel Mwangi",
    senderRole: "Program Lead",
    kind: "feedback",
    subject: "Strong delivery this week — keep it up",
    preview: "Just a note to say your follow-up coaching visits at Hope and Grace have shown up clean in the inbox...",
    body:
      "Just a note to say your follow-up coaching visits at Hope and Grace have shown up clean in the inbox. CCEO confirmation is moving fast and payment is on track. Keep the same evidence quality.\n\n— Daniel (PL)",
    sentAt: "Yesterday · 4:12 PM",
    unread: true,
  },
  {
    id: "M-3",
    sender: "Sarah Nanyongo",
    senderRole: "CCEO",
    kind: "reminder",
    subject: "Schedule reminder — Maple Grove coaching visit",
    preview: "Reminder: Maple Grove (Kayunga) literacy follow-up is still unscheduled 5 days after assignment...",
    body:
      "Reminder: Maple Grove (Kayunga) literacy follow-up is still unscheduled 5 days after assignment. Please add it to a delivery week so I can monitor delivery.\n\n— Sarah",
    sentAt: "May 12 · 2:01 PM",
    unread: false,
  },
  {
    id: "M-4",
    sender: "Grace Alimo",
    senderRole: "M&E",
    kind: "feedback",
    subject: "M&E verified 4 May activities — counted in May report",
    preview: "Quick heads-up — your Namilyango resource delivery and Eastview follow-up have been verified by M&E...",
    body:
      "Quick heads-up — your Namilyango resource delivery, Eastview follow-up, Mukono Central observation, and Bright Future delivery have all been verified by M&E and will count in the May impact report.\n\n— Grace, M&E",
    sentAt: "May 11 · 11:45 AM",
    unread: false,
  },
  {
    id: "M-5",
    sender: "Sarah Nanyongo",
    senderRole: "CCEO",
    kind: "coordination",
    subject: "Joint visit proposal — Bbaale cluster (May 28)",
    preview: "I'd like to join your team for the Bbaale cluster visit on May 28 — quick alignment on coaching focus...",
    body:
      "I'd like to join your team for the Bbaale cluster visit on May 28 — quick alignment on coaching focus areas so the partner-led work and CCEO follow-up tell one story.\n\nLet me know if 9am at Bbaale Primary works.\n\n— Sarah",
    sentAt: "May 10 · 8:20 AM",
    unread: false,
  },
  {
    id: "M-6",
    sender: "Moses Tindi",
    senderRole: "Accountant",
    kind: "feedback",
    subject: "April payment batch cleared — UGX 5.6M",
    preview: "The April payment batch (16 activities) has cleared. Bank ref BANK-2026-04832. May batch is in queue...",
    body:
      "The April payment batch (16 activities) has cleared. Bank ref BANK-2026-04832. May batch is in queue — 2 ready, 5 awaiting PL approval, 3 awaiting CCEO confirmation.\n\n— Moses, Accountant",
    sentAt: "May 09 · 5:55 PM",
    unread: false,
  },
];

const ROLE_TONE: Record<Message["senderRole"], string> = {
  "CCEO":         "bg-[var(--color-edify-soft)] text-[var(--color-edify-primary)]",
  "Program Lead": "bg-violet-50 text-violet-700",
  "M&E":          "bg-emerald-50 text-emerald-700",
  "Accountant":   "bg-amber-50 text-amber-700",
};

export function PartnerMessagesList() {
  const [selected, setSelected] = useState<string>(MESSAGES[0].id);
  const [filter, setFilter] = useState<"all" | "unread">("all");

  const visible = filter === "unread" ? MESSAGES.filter((m) => m.unread) : MESSAGES;
  const active = MESSAGES.find((m) => m.id === selected) ?? MESSAGES[0];

  const unreadCount = MESSAGES.filter((m) => m.unread).length;
  const activeKind = KIND_ACCENT[active.kind];

  return (
    <section className="card rounded-2xl p-0 overflow-hidden">
      <div className="grid grid-cols-12 min-h-[580px]">
        {/* ─────────── List pane ─────────── */}
        <aside className="col-span-12 lg:col-span-5 border-b lg:border-b-0 lg:border-r border-[var(--color-edify-divider)] flex flex-col">
          <header className="px-4 pt-4 pb-3 flex items-center justify-between gap-3">
            <div className="flex items-baseline gap-2 min-w-0">
              <h3 className="text-[15px] font-extrabold tracking-tight">Inbox</h3>
              {unreadCount > 0 && (
                <span className="text-[11.5px] muted tabular">{unreadCount} unread</span>
              )}
            </div>
            <div className="inline-flex items-center rounded-md bg-[var(--color-edify-soft)]/60 p-0.5">
              {(["all", "unread"] as const).map((f) => {
                const isActive = filter === f;
                return (
                  <button
                    key={f}
                    type="button"
                    onClick={() => setFilter(f)}
                    className={cn(
                      "h-7 px-2.5 rounded-[5px] text-[11px] font-semibold transition-colors",
                      isActive
                        ? "bg-white text-[var(--color-edify-text)] shadow-[0_1px_2px_rgba(15,23,32,0.06)]"
                        : "text-[var(--color-edify-muted)] hover:text-[var(--color-edify-text)]",
                    )}
                  >
                    {f === "all" ? "All" : "Unread"}
                  </button>
                );
              })}
            </div>
          </header>

          <ul className="flex-1 overflow-y-auto">
            {visible.map((m) => {
              const isActiveRow = m.id === selected;
              const kind = KIND_ACCENT[m.kind];
              return (
                <li key={m.id}>
                  <button
                    type="button"
                    onClick={() => setSelected(m.id)}
                    className={cn(
                      // 3px coloured accent strip on the leading edge for
                      // unread messages — premium email-client pattern.
                      // Read rows get a faint inset only on hover.
                      "relative w-full text-left px-4 py-3.5 transition-colors",
                      "before:absolute before:left-0 before:top-0 before:bottom-0 before:w-[3px] before:transition-opacity",
                      m.unread ? cn("before:opacity-100", kind.stripe) : "before:opacity-0",
                      isActiveRow
                        ? "bg-[var(--color-edify-soft)]/55"
                        : "hover:bg-[var(--color-edify-soft)]/30",
                    )}
                  >
                    <div className="flex items-start justify-between gap-3">
                      <div
                        className={cn(
                          "text-[13px] tracking-tight truncate",
                          m.unread ? "font-extrabold text-[var(--color-edify-text)]" : "font-semibold text-[var(--color-edify-text)]/85",
                        )}
                      >
                        {m.sender}
                      </div>
                      <span className="text-caption text-[var(--color-edify-muted)] tabular whitespace-nowrap pt-0.5">
                        {m.sentAt.split(" · ")[0]}
                      </span>
                    </div>
                    <div
                      className={cn(
                        "text-body mt-1 leading-snug line-clamp-1",
                        m.unread ? "font-bold text-[var(--color-edify-text)]" : "text-[var(--color-edify-text)]/75",
                      )}
                    >
                      {m.subject}
                    </div>
                    <div className="text-[11.5px] text-[var(--color-edify-muted)] leading-snug mt-1 line-clamp-1">
                      {m.preview}
                    </div>
                    <div className="flex items-center gap-2 mt-2">
                      <span
                        className={cn(
                          "inline-flex items-center px-1.5 py-[1px] rounded-md text-[9.5px] font-extrabold uppercase tracking-[0.06em]",
                          ROLE_TONE[m.senderRole],
                        )}
                      >
                        {m.senderRole}
                      </span>
                      <span className="inline-flex items-center gap-1 text-caption text-[var(--color-edify-muted)] font-semibold">
                        <span className={cn("h-1.5 w-1.5 rounded-full", kind.dot)} />
                        {kind.label}
                      </span>
                    </div>
                  </button>
                </li>
              );
            })}
          </ul>
        </aside>

        {/* ─────────── Reader pane ─────────── */}
        <article className="col-span-12 lg:col-span-7 flex flex-col">
          <header className="px-5 lg:px-6 pt-6 pb-5 border-b border-[var(--color-edify-divider)]">
            <div className="flex items-center gap-2 text-caption text-[var(--color-edify-muted)] font-semibold mb-2">
              <span className={cn("h-1.5 w-1.5 rounded-full", activeKind.dot)} />
              <span className="uppercase tracking-[0.08em]">{activeKind.label}</span>
            </div>
            <h2 className="text-[18px] lg:text-[20px] font-extrabold tracking-tight leading-snug text-balance">
              {active.subject}
            </h2>
            <div className="flex items-center gap-2 mt-3 text-[11.5px] text-[var(--color-edify-muted)]">
              <span className="font-semibold text-[var(--color-edify-text)]">{active.sender}</span>
              <span>·</span>
              <span
                className={cn(
                  "inline-flex items-center px-1.5 py-[1px] rounded-md text-[9.5px] font-extrabold uppercase tracking-[0.06em]",
                  ROLE_TONE[active.senderRole],
                )}
              >
                {active.senderRole}
              </span>
              <span>·</span>
              <span className="tabular">{active.sentAt}</span>
            </div>
          </header>

          <div className="px-5 lg:px-6 py-6 flex-1 text-body-lg text-[var(--color-edify-text)] leading-[1.7] whitespace-pre-wrap">
            {active.body}
          </div>

          <footer className="px-5 lg:px-6 py-4 border-t border-[var(--color-edify-divider)] flex items-center justify-between gap-3">
            <p className="text-[11px] text-[var(--color-edify-muted)] leading-snug max-w-[320px]">
              Replies route through your CCEO focal — we keep the chain auditable.
            </p>
            <button
              type="button"
              className="inline-flex items-center gap-1.5 h-9 px-3.5 rounded-lg bg-[var(--color-edify-primary)] text-white text-body font-extrabold hover:bg-[var(--color-edify-dark)] shadow-[0_1px_2px_rgba(15,23,32,0.06)]"
            >
              <CornerUpLeft size={13} />
              Reply
            </button>
          </footer>
        </article>
      </div>
    </section>
  );
}
