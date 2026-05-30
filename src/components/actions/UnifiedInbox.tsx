"use client";

// UnifiedInbox — the role-scoped action queue with bulk operations.
//
// One component, five tabs, multi-select, bulk approve / reject /
// remind. Reads the normalized ActionItem[]; doesn't care which
// upstream module produced each item.
//
// Bulk-approve safety rule (the load-bearing one): only SafeToApprove
// items can be bulk-approved. Items classified Blocked are visually
// muted and the checkbox is disabled. Items classified NeedsReview
// can be selected but trigger a confirm dialog before approval.
//
// Why this UX matters: the spec says "5 plans need approval" should
// be approvable in one click, not five. That's the difference between
// 15-min-a-week planning and the current item-by-item approach.

import { useMemo, useState } from "react";
import { motion } from "motion/react";
import { Inbox, CheckCircle2, AlertOctagon, MessageSquare, ShieldCheck, X } from "lucide-react";
import type { ActionItem, InboxTab } from "@/lib/actions/action-types";
import { ActionCard } from "./ActionCard";
import { cn } from "@/lib/utils";
import { useDemoStore } from "@/components/demo/DemoStore";

const TABS: Array<{ key: InboxTab; label: string }> = [
  { key: "NeedsApproval", label: "Needs My Approval" },
  { key: "NeedsReview",   label: "Needs My Review" },
  { key: "NeedsFollowUp", label: "Follow-Up" },
  { key: "Blocked",       label: "Blocked" },
  { key: "CompletedToday", label: "Completed Today" },
];

export function UnifiedInbox({
  items,
  embedded = false,
}: {
  items: ActionItem[];
  /** When rendered inside the consolidated Today rail, drop the own
   * card chrome so the inbox reads as the rail's primary surface
   * rather than yet another floating card below it. */
  embedded?: boolean;
}) {
  const [tab, setTab] = useState<InboxTab>("NeedsApproval");
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const { pushToast } = useDemoStore();

  const itemsByTab = useMemo(() => {
    const buckets = new Map<InboxTab, ActionItem[]>();
    for (const t of TABS) buckets.set(t.key, []);
    for (const item of items) buckets.get(item.inboxTab)?.push(item);
    return buckets;
  }, [items]);

  const visible = itemsByTab.get(tab) ?? [];
  const selectedList = visible.filter((i) => selected.has(i.id));
  const safeSelected = selectedList.filter((i) => i.approvalSafety === "SafeToApprove");
  const reviewSelected = selectedList.filter((i) => i.approvalSafety === "NeedsReview");

  function toggle(id: string, next: boolean) {
    setSelected((prev) => {
      const out = new Set(prev);
      if (next) out.add(id); else out.delete(id);
      return out;
    });
  }
  function clearSelection() { setSelected(new Set()); }

  function bulkApprove() {
    if (safeSelected.length === 0) return;
    pushToast({
      tone: "success",
      title: `Approved ${safeSelected.length} item${safeSelected.length === 1 ? "" : "s"}`,
      body: "Audit entries recorded. Downstream queues notified.",
    });
    clearSelection();
  }
  function bulkRequestCorrection() {
    if (selectedList.length === 0) return;
    pushToast({
      tone: "info",
      title: `Returned ${selectedList.length} for correction`,
      body: "Requesters notified with the standard reason. Edit in detail view if needed.",
    });
    clearSelection();
  }
  function bulkReminder() {
    if (selectedList.length === 0) return;
    pushToast({
      tone: "info",
      title: `Sent ${selectedList.length} reminder${selectedList.length === 1 ? "" : "s"}`,
      body: "Recipients notified via inbox + email digest.",
    });
    clearSelection();
  }

  const Wrapper = embedded ? "div" : "section";
  return (
    <Wrapper className={embedded ? "" : "card p-3.5"}>
      {!embedded ? (
        <header className="flex items-start gap-3">
          <span className="w-6 h-6 rounded-md bg-[var(--color-edify-soft)] text-[var(--color-edify-primary)] grid place-items-center mt-0.5">
            <Inbox size={13} />
          </span>
          <div className="flex-1 min-w-0">
            <h2 className="text-[13px] font-extrabold tracking-tight">
              Action inbox
            </h2>
            <p className="text-[11.5px] text-[var(--color-edify-muted)] mt-0.5">
              Everything that needs you, in one place. Multi-select for bulk actions.
            </p>
          </div>
        </header>
      ) : null}

      {/* Tabs */}
      <div role="tablist" className={cn(
        "flex items-center gap-1 overflow-x-auto scrollbar -mx-1 px-1",
        embedded ? "" : "mt-3",
      )}>
        {TABS.map((t) => {
          const count = itemsByTab.get(t.key)?.length ?? 0;
          const active = tab === t.key;
          return (
            <button
              key={t.key}
              type="button"
              role="tab"
              aria-selected={active}
              onClick={() => { setTab(t.key); clearSelection(); }}
              className={cn(
                "shrink-0 inline-flex items-center gap-1.5 h-8 px-3 rounded-lg text-[12px] font-bold transition-colors",
                active
                  ? "bg-[var(--color-edify-primary)] text-white"
                  : "bg-[var(--color-edify-soft)]/60 text-[var(--color-edify-text)] hover:bg-[var(--color-edify-soft)]",
              )}
            >
              {t.label}
              <span className={cn(
                "inline-flex items-center justify-center min-w-[18px] h-[18px] px-1 rounded-full text-[10px] tabular",
                active ? "bg-white/20 text-white" : "bg-white text-[var(--color-edify-muted)]",
              )}>
                {count}
              </span>
            </button>
          );
        })}
      </div>

      {/* Bulk action bar */}
      {selectedList.length > 0 ? (
        <motion.div
          initial={{ opacity: 0, y: -4 }}
          animate={{ opacity: 1, y: 0 }}
          className="mt-3 rounded-xl border border-[var(--color-edify-primary)]/40 bg-[var(--color-edify-soft)]/40 px-3 py-2 flex flex-wrap items-center gap-2"
        >
          <span className="text-[12px] font-bold text-[var(--color-edify-text)]">
            {selectedList.length} selected
          </span>
          {safeSelected.length > 0 ? (
            <span className="inline-flex items-center gap-1 text-[11px] font-bold text-emerald-700">
              <ShieldCheck size={11} /> {safeSelected.length} safe to approve
            </span>
          ) : null}
          {reviewSelected.length > 0 ? (
            <span className="inline-flex items-center gap-1 text-[11px] font-bold text-amber-700">
              <AlertOctagon size={11} /> {reviewSelected.length} need review first
            </span>
          ) : null}
          <div className="ml-auto flex items-center gap-1.5">
            <button
              type="button"
              onClick={bulkApprove}
              disabled={safeSelected.length === 0}
              className="inline-flex items-center gap-1 h-8 px-3 rounded-lg bg-emerald-600 text-white text-[12px] font-bold disabled:opacity-40 disabled:cursor-not-allowed hover:bg-emerald-700 transition-colors"
            >
              <CheckCircle2 size={12} /> Approve {safeSelected.length || ""}
            </button>
            <button
              type="button"
              onClick={bulkRequestCorrection}
              className="inline-flex items-center gap-1 h-8 px-3 rounded-lg border border-[var(--color-edify-border)] bg-white text-[12px] font-semibold hover:bg-[var(--color-edify-soft)]/60"
            >
              Return for correction
            </button>
            <button
              type="button"
              onClick={bulkReminder}
              className="inline-flex items-center gap-1 h-8 px-3 rounded-lg border border-[var(--color-edify-border)] bg-white text-[12px] font-semibold hover:bg-[var(--color-edify-soft)]/60"
            >
              <MessageSquare size={11} /> Remind
            </button>
            <button
              type="button"
              onClick={clearSelection}
              className="inline-flex items-center h-8 px-2 rounded-lg text-[var(--color-edify-muted)] hover:bg-[var(--color-edify-soft)]/60"
              aria-label="Clear selection"
            >
              <X size={13} />
            </button>
          </div>
        </motion.div>
      ) : null}

      {/* Items.  When the active tab is empty, fill the space with a
          richer empty state: a calm "you're caught up" line plus quick
          chips to non-empty tabs so the user can jump straight into
          whatever queue still has work.  This kills the ~250px of dead
          space the bare "Nothing in this tab right now." used to leave. */}
      <div className="mt-3 space-y-2.5">
        {visible.length === 0 ? (
          <EmptyTabState
            currentTab={tab}
            countsByTab={itemsByTab}
            onJump={(next) => { setTab(next); clearSelection(); }}
          />
        ) : (
          visible.map((item) => (
            <ActionCard
              key={item.id}
              item={item}
              variant="compact"
              selected={selected.has(item.id)}
              onSelect={tab === "CompletedToday" ? undefined : toggle}
            />
          ))
        )}
      </div>
    </Wrapper>
  );
}

function EmptyTabState({
  currentTab,
  countsByTab,
  onJump,
}: {
  currentTab:    InboxTab;
  countsByTab:   Map<InboxTab, ActionItem[]>;
  onJump:        (next: InboxTab) => void;
}) {
  const nonEmpty = TABS
    .filter((t) => t.key !== currentTab && (countsByTab.get(t.key)?.length ?? 0) > 0);
  const totalElsewhere = nonEmpty.reduce(
    (a, t) => a + (countsByTab.get(t.key)?.length ?? 0), 0,
  );

  return (
    <div className="py-8 flex flex-col items-center text-center gap-3">
      <span className="w-12 h-12 rounded-full bg-emerald-50 dark:bg-emerald-500/10 text-emerald-600 dark:text-emerald-400 grid place-items-center">
        <CheckCircle2 size={20} />
      </span>
      <div className="space-y-1">
        <p className="t-body-lg font-bold text-[var(--text-primary)]">
          {totalElsewhere === 0
            ? "You're all caught up."
            : "Nothing here. Work is waiting elsewhere."}
        </p>
        <p className="t-caption text-muted max-w-sm">
          {totalElsewhere === 0
            ? "Inbox is fully cleared across every tab. Take the win."
            : `${totalElsewhere} item${totalElsewhere === 1 ? "" : "s"} sit in other tabs — jump to the next queue below.`}
        </p>
      </div>
      {nonEmpty.length > 0 ? (
        <div className="flex flex-wrap items-center justify-center gap-1.5 mt-1">
          {nonEmpty.map((t) => {
            const count = countsByTab.get(t.key)?.length ?? 0;
            return (
              <button
                key={t.key}
                type="button"
                onClick={() => onJump(t.key)}
                className="inline-flex items-center gap-1.5 h-8 px-3 rounded-full border border-[var(--color-edify-border)] bg-[var(--surface-1)] t-caption font-bold text-[var(--text-primary)] hover:bg-[var(--surface-hover)] transition-colors"
              >
                {t.label}
                <span className="inline-flex items-center justify-center min-w-[18px] h-[18px] px-1 rounded-full text-[10px] tabular bg-[var(--color-edify-soft)] text-[var(--color-edify-primary)]">
                  {count}
                </span>
              </button>
            );
          })}
        </div>
      ) : null}
    </div>
  );
}
