"use client";

// MessageCompose — premium, calm message-writing surface.
//
// The "To" picker searches the directory (name / email / role / scope
// / org) and only suggests users the sender is allowed to message
// per the role-rules in `lib/messages-v2/directory.recipientsForSender`.
// This enforces the spec's section 5 rules in the UI as well as on
// the server.
//
// Submit is mock today — logs + redirects to the sent folder. Phase 2
// wires this into a real persistence layer.

import { useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { AlertTriangle, CheckCircle2, Layers, Search, Send, Sparkles, Square, SquareCheck, Tag, X } from "lucide-react";
import { cn } from "@/lib/utils";
import { CATEGORY_META } from "@/lib/messages-v2/categories";
import {
  categoriesForRole,
  contextTypesForCategory,
  searchContextRecords,
  type ContextOption,
} from "@/lib/messages-v2/contexts";
import {
  recipientsForSender,
  searchDirectory,
  type DirectoryUser,
} from "@/lib/messages-v2/directory";
import { suggestedReceivers, type Suggestion } from "@/lib/messages-v2/suggestions";
import { PRIORITIES } from "@/lib/debrief/priorities";
import type {
  MessageCategory,
  MessagePriority,
} from "@/lib/messages-v2/types";
import type { EdifyRole } from "@/lib/auth-public";

type SendMode = "one_thread" | "separate_threads";

export function MessageCompose({
  senderRole,
  senderName,
  senderEmail,
  /** Where to return to once the message is sent or cancelled. */
  backHref = "/partner/messages",
  /** Server action that persists the message and redirects to the
   *  new message's detail page. The composer constructs FormData and
   *  hands it off — this keeps the client UX (validation, loading)
   *  while routing the write through the spec's permission re-check. */
  sendAction,
}: {
  senderRole:  EdifyRole;
  senderName:  string;
  senderEmail: string;
  backHref?:   string;
  sendAction:  (formData: FormData) => Promise<void> | void;
}) {
  const router = useRouter();
  const allowed = useMemo(() => recipientsForSender(senderRole), [senderRole]);
  const allowedCategories = useMemo(() => categoriesForRole(senderRole), [senderRole]);

  const [picked, setPicked] = useState<DirectoryUser[]>([]);
  const [query, setQuery] = useState("");
  const [subject, setSubject] = useState("");
  const [body, setBody] = useState("");
  // Default category is the first one the role is allowed to use, so
  // the dropdown is never empty / out-of-scope.
  const [category, setCategory] = useState<MessageCategory>(allowedCategories[0] ?? "general");
  const [priority, setPriority] = useState<MessagePriority>("Normal");
  const [submitting, setSubmitting] = useState(false);

  // ─── Context (spec section 1–3 + bulk): required on every new message ───
  //
  // Multi-select: a list of picked context records. Single-context
  // sends end up with one entry; bulk-context sends end up with N.
  const [pickedContexts, setPickedContexts] = useState<ContextOption[]>([]);
  const [contextQuery, setContextQuery] = useState("");
  const validContextTypes = useMemo(() => contextTypesForCategory(category), [category]);
  const contextSuggestions = useMemo(
    () => searchContextRecords(validContextTypes, contextQuery).slice(0, 12),
    [validContextTypes, contextQuery],
  );
  const isPicked = (id: string) => pickedContexts.some((c) => c.id === id);
  function toggleContext(o: ContextOption) {
    setPickedContexts((prev) =>
      prev.some((c) => c.id === o.id)
        ? prev.filter((c) => c.id !== o.id)
        : [...prev, o],
    );
  }
  function selectAllVisible() {
    setPickedContexts((prev) => {
      const ids = new Set(prev.map((c) => c.id));
      const next = [...prev];
      for (const o of contextSuggestions) if (!ids.has(o.id)) next.push(o);
      return next;
    });
  }
  function clearContexts() {
    setPickedContexts([]);
  }

  // Send mode — only meaningful when ≥2 contexts are picked.
  // Default: payment / evidence / correction → separate threads (each
  // record needs its own audit trail). Everything else → one grouped
  // thread.
  const isPerRecordCategory =
    category === "payment-update" || category === "finance" ||
    category === "evidence-review" || category === "correction-request";
  const [sendMode, setSendMode] = useState<SendMode>(isPerRecordCategory ? "separate_threads" : "one_thread");

  // Clear picked contexts when the user switches to a category whose
  // valid types don't include them. Also re-default the send-mode
  // based on the new category's per-record-ness.
  function changeCategory(next: MessageCategory) {
    setCategory(next);
    const allowedTypes = contextTypesForCategory(next);
    setPickedContexts((prev) => prev.filter((c) => allowedTypes.includes(c.type)));
    const perRecord = next === "payment-update" || next === "finance"
      || next === "evidence-review" || next === "correction-request";
    setSendMode(perRecord ? "separate_threads" : "one_thread");
  }

  // ─── Receiver suggestions ───
  //
  // Driven by the chosen contexts + category + sender role. Primary
  // recipients are pre-checked; optional ones are opt-in via
  // checkbox. Manual additions via the search picker stack on top.
  const receiverSuggestions = useMemo(
    () =>
      pickedContexts.length === 0
        ? { primary: [], optional: [] }
        : suggestedReceivers(pickedContexts, category, senderRole),
    [pickedContexts, category, senderRole],
  );

  // Accepted primary suggestions auto-fill the `picked` list. Phase 1:
  // we simply pre-fill on first change. The user can remove anyone
  // they don't want from the To chip strip above.
  function acceptSuggestion(s: Suggestion) {
    if (!picked.find((p) => p.userId === s.user.userId)) {
      setPicked((prev) => [...prev, s.user]);
    }
  }
  function acceptAllPrimary() {
    const toAdd = receiverSuggestions.primary.filter(
      (s) => !picked.find((p) => p.userId === s.user.userId),
    );
    if (toAdd.length === 0) return;
    setPicked((prev) => [...prev, ...toAdd.map((s) => s.user)]);
  }

  const suggestions = useMemo(() => {
    if (query.trim().length === 0) return [];
    return searchDirectory(allowed, query)
      .filter((u) => !picked.find((p) => p.userId === u.userId))
      .slice(0, 6);
  }, [allowed, query, picked]);

  const canSubmit =
    picked.length > 0 &&
    pickedContexts.length > 0 &&
    subject.trim().length > 0 &&
    body.trim().length > 0 &&
    !submitting;

  // Spec section 10: the disabled-state message tells the user
  // exactly which field is blocking the send.
  const blockingMessage =
    pickedContexts.length === 0 ? "Add message context before sending." :
    picked.length === 0         ? "Add a recipient before sending." :
    subject.trim().length === 0 ? "Add a subject before sending." :
    body.trim().length === 0    ? "Write a message before sending." :
    null;

  function addRecipient(u: DirectoryUser) {
    setPicked((prev) => [...prev, u]);
    setQuery("");
  }
  function removeRecipient(userId: string) {
    setPicked((prev) => prev.filter((p) => p.userId !== userId));
  }

  // Two-stage submit for bulk sends. If the user is about to create
  // multiple threads (separate_threads + >1 context), intercept the
  // first click and show a preview. A second click confirms.
  const [previewing, setPreviewing] = useState(false);
  const willCreateMultipleThreads =
    pickedContexts.length > 1 && sendMode === "separate_threads";

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!canSubmit || pickedContexts.length === 0) return;
    // First click on a multi-thread send → show preview, don't submit yet.
    if (willCreateMultipleThreads && !previewing) {
      setPreviewing(true);
      return;
    }
    setSubmitting(true);
    const fd = new FormData();
    fd.append("subject", subject);
    fd.append("body", body);
    fd.append("category", category);
    fd.append("priority", priority);
    fd.append("recipientEmails", picked.map((u) => u.email).join(","));
    // Multi-context: ship parallel arrays. The server splits on "|"
    // (comma is reserved for email lists). The legacy single-context
    // fields stay populated from index 0 for back-compat with the
    // existing server action shape.
    fd.append("contextType",   pickedContexts[0].type);
    fd.append("contextId",     pickedContexts[0].id);
    fd.append("contextLabel",  pickedContexts[0].label);
    fd.append("contextTypes",  pickedContexts.map((c) => c.type).join("|"));
    fd.append("contextIds",    pickedContexts.map((c) => c.id).join("|"));
    fd.append("contextLabels", pickedContexts.map((c) => c.label).join("|"));
    fd.append("sendMode", pickedContexts.length > 1 ? sendMode : "one_thread");
    fd.append("backHref", backHref);
    // Server action redirects on success — control doesn't return.
    // On unexpected failure we surface the error and reset state.
    try {
      await sendAction(fd);
    } catch (err) {
      // eslint-disable-next-line no-console
      console.error("[message] send failed", err);
      setSubmitting(false);
    }
  }

  return (
    <form onSubmit={handleSubmit} className="space-y-4 max-w-[820px]">
      {/* Header — sender identity */}
      <header className="card p-3.5 lg:p-5 flex items-center justify-between gap-3 flex-wrap">
        <div className="min-w-0">
          <div className="text-caption font-bold uppercase tracking-[0.08em] text-[var(--color-edify-muted)]">From</div>
          <div className="mt-1 text-[13.5px] font-extrabold tracking-tight">{senderName}</div>
          <div className="text-[11.5px] text-[var(--color-edify-muted)]">{senderEmail}</div>
        </div>
        <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-emerald-50 border border-emerald-200 text-emerald-700 text-[11px] font-semibold">
          <CheckCircle2 size={11} />
          Internal — stays in app
        </span>
      </header>

      {/* To picker */}
      <section className="card p-3.5 lg:p-5">
        <label className="text-body font-extrabold tracking-tight">To</label>
        <p className="text-[11px] text-[var(--color-edify-muted)] mt-0.5">
          Search registered users by name, email, role, or scope. Only people you're allowed to message appear.
        </p>

        {picked.length > 0 && (
          <ul className="mt-3 flex flex-wrap gap-1.5">
            {picked.map((u) => (
              <li key={u.userId}>
                <span className="inline-flex items-center gap-1.5 h-7 pl-2.5 pr-1 rounded-full bg-[var(--color-edify-soft)] border border-[var(--color-edify-border)] text-[11.5px] font-semibold">
                  <span className="font-extrabold">{u.name}</span>
                  <span className="text-caption text-[var(--color-edify-muted)]">{u.email}</span>
                  <button
                    type="button"
                    onClick={() => removeRecipient(u.userId)}
                    aria-label={`Remove ${u.name}`}
                    className="ml-0.5 h-5 w-5 rounded-full grid place-items-center hover:bg-rose-50 hover:text-rose-700 text-[var(--color-edify-muted)]"
                  >
                    <X size={11} />
                  </button>
                </span>
              </li>
            ))}
          </ul>
        )}

        <div className="relative mt-3">
          <input
            type="text"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Type a name, email, role, or scope…"
            className="h-10 w-full px-3 rounded-lg border border-[var(--color-edify-border)] bg-white text-body placeholder:text-[var(--color-edify-muted)] focus:outline-none focus:ring-2 focus:ring-[var(--color-edify-primary)]/30"
          />
          {suggestions.length > 0 && (
            <ul className="absolute left-0 right-0 top-[calc(100%+4px)] z-20 card rounded-xl max-h-[280px] overflow-y-auto divide-y divide-[var(--color-edify-divider)]">
              {suggestions.map((u) => (
                <li key={u.userId}>
                  <button
                    type="button"
                    onClick={() => addRecipient(u)}
                    className="w-full text-left px-3.5 py-2.5 hover:bg-[var(--color-edify-soft)]/40 transition-colors"
                  >
                    <div className="flex items-center justify-between gap-3 flex-wrap">
                      <div className="min-w-0">
                        <div className="text-body font-extrabold tracking-tight truncate">{u.name}</div>
                        <div className="text-[11px] text-[var(--color-edify-muted)] truncate">{u.email}</div>
                      </div>
                      <span className="text-caption uppercase tracking-[0.06em] font-extrabold text-[var(--color-edify-muted)] whitespace-nowrap">
                        {u.displayRole}
                      </span>
                    </div>
                    <div className="text-caption text-[var(--color-edify-muted)] mt-1 truncate">{u.scope}</div>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      </section>

      {/* Category + priority — placed BEFORE Context so the category
          choice drives which context types are valid. */}
      <section className="card p-3.5 lg:p-5 grid grid-cols-1 md:grid-cols-2 gap-4">
        <div>
          <label className="text-body font-extrabold tracking-tight">Category</label>
          <select
            value={category}
            onChange={(e) => changeCategory(e.target.value as MessageCategory)}
            className="mt-1.5 h-10 w-full px-3 rounded-lg border border-[var(--color-edify-border)] bg-white text-body focus:outline-none focus:ring-2 focus:ring-[var(--color-edify-primary)]/30"
          >
            {allowedCategories.map((key) => {
              const c = CATEGORY_META[key];
              return <option key={key} value={key}>{c.label}</option>;
            })}
          </select>
        </div>
        <div>
          <label className="text-body font-extrabold tracking-tight">Priority</label>
          <div className="mt-1.5 grid grid-cols-2 gap-1.5">
            {PRIORITIES.map((p) => {
              const active = priority === p.key;
              return (
                <button
                  key={p.key}
                  type="button"
                  onClick={() => setPriority(p.key)}
                  className={cn(
                    "h-9 px-2.5 rounded-lg border text-[11.5px] font-semibold transition-colors text-left",
                    active
                      ? "bg-[var(--color-edify-primary)] border-[var(--color-edify-primary)] text-white"
                      : "bg-white border-[var(--color-edify-border)] hover:bg-[var(--color-edify-soft)]/40",
                  )}
                >
                  {p.label}
                </button>
              );
            })}
          </div>
        </div>
      </section>

      {/* Context — REQUIRED. Bulk-capable. Replies inherit and skip
          this entirely (see MessageReplyBox). */}
      <section className="card p-3.5 lg:p-5">
        <div className="flex items-center justify-between gap-3 flex-wrap">
          <div>
            <label className="text-body font-extrabold tracking-tight inline-flex items-center gap-1.5">
              <Tag size={12} className="text-[var(--color-edify-muted)]" />
              Context
              <span className="text-[10px] font-bold uppercase tracking-[0.06em] text-rose-700 bg-rose-50 border border-rose-200 px-1.5 py-[1px] rounded-md">Required</span>
            </label>
            <p className="text-[11px] text-[var(--color-edify-muted)] mt-0.5">
              What is this message about? Pick one or many — the thread inherits this context so every reply stays connected.
            </p>
          </div>
          {pickedContexts.length > 0 && (
            <button
              type="button"
              onClick={clearContexts}
              className="h-7 px-2.5 rounded-md text-[11px] font-semibold text-[var(--color-edify-muted)] hover:text-[var(--color-edify-text)] hover:bg-[var(--color-edify-soft)]/40"
            >
              Clear ({pickedContexts.length})
            </button>
          )}
        </div>

        {/* Selected chips strip */}
        {pickedContexts.length > 0 && (
          <ul className="mt-3 flex flex-wrap gap-1.5">
            {pickedContexts.map((c) => (
              <li key={c.id}>
                <span className="inline-flex items-center gap-1.5 h-7 pl-2.5 pr-1 rounded-full bg-[var(--color-edify-soft)] border border-[var(--color-edify-border)] text-[11.5px] font-semibold">
                  <span className="text-[10px] uppercase tracking-[0.06em] font-extrabold text-[var(--color-edify-muted)]">
                    {contextTypeLabel(c.type)}
                  </span>
                  <span>{c.label}</span>
                  <button
                    type="button"
                    onClick={() => toggleContext(c)}
                    aria-label={`Remove ${c.label}`}
                    className="ml-0.5 h-5 w-5 rounded-full grid place-items-center hover:bg-rose-50 hover:text-rose-700 text-[var(--color-edify-muted)]"
                  >
                    <X size={11} />
                  </button>
                </span>
              </li>
            ))}
          </ul>
        )}

        {/* Search + checkbox list */}
        <div className="mt-3">
          <div className="relative">
            <Search size={13} className="absolute left-3 top-1/2 -translate-y-1/2 text-[var(--color-edify-muted)] pointer-events-none" />
            <input
              type="text"
              value={contextQuery}
              onChange={(e) => setContextQuery(e.target.value)}
              placeholder={`Search ${validContextTypes.map(contextTypeLabel).slice(0, 3).join(" / ").toLowerCase()}…`}
              className="h-10 w-full pl-9 pr-3 rounded-lg border border-[var(--color-edify-border)] bg-white text-body placeholder:text-[var(--color-edify-muted)] focus:outline-none focus:ring-2 focus:ring-[var(--color-edify-primary)]/30"
            />
          </div>
          {contextSuggestions.length > 0 && (
            <>
              <div className="mt-2 flex items-center justify-between gap-3 px-1">
                <span className="text-[11px] text-[var(--color-edify-muted)]">
                  {contextSuggestions.length} {validContextTypes[0] ? contextTypeLabel(validContextTypes[0]).toLowerCase() : ""} match{contextSuggestions.length === 1 ? "" : "es"}
                  {contextQuery && ` for "${contextQuery}"`}
                </span>
                <button
                  type="button"
                  onClick={selectAllVisible}
                  className="text-[11px] font-semibold text-[var(--color-edify-primary)] hover:underline"
                >
                  Select all visible
                </button>
              </div>
              <ul className="mt-1.5 card rounded-xl max-h-[320px] overflow-y-auto divide-y divide-[var(--color-edify-divider)]">
                {contextSuggestions.map((o) => {
                  const checked = isPicked(o.id);
                  return (
                    <li key={o.id}>
                      <button
                        type="button"
                        onClick={() => toggleContext(o)}
                        className={cn(
                          "w-full text-left px-3.5 py-2.5 transition-colors flex items-center gap-3",
                          checked ? "bg-[var(--color-edify-soft)]/40" : "hover:bg-[var(--color-edify-soft)]/30",
                        )}
                      >
                        <span className={cn("shrink-0", checked ? "text-[var(--color-edify-primary)]" : "text-[var(--color-edify-muted)]")}>
                          {checked ? <SquareCheck size={16} /> : <Square size={16} />}
                        </span>
                        <div className="flex items-center justify-between gap-3 flex-wrap flex-1 min-w-0">
                          <div className="min-w-0">
                            <div className="text-body font-extrabold tracking-tight truncate">{o.label}</div>
                          </div>
                          <span className="text-[10px] uppercase tracking-[0.06em] font-extrabold text-[var(--color-edify-muted)] whitespace-nowrap">
                            {contextTypeLabel(o.type)}
                          </span>
                        </div>
                      </button>
                    </li>
                  );
                })}
              </ul>
            </>
          )}
        </div>

        {/* Bulk send-mode toggle — only when ≥2 contexts are picked. */}
        {pickedContexts.length > 1 && (
          <div className="mt-4 pt-4 border-t border-[var(--color-edify-divider)]">
            <div className="text-body font-extrabold tracking-tight inline-flex items-center gap-1.5">
              <Layers size={12} className="text-[var(--color-edify-muted)]" />
              Send as
            </div>
            <p className="text-[11px] text-[var(--color-edify-muted)] mt-0.5">
              {pickedContexts.length} contexts selected — choose how to deliver.
            </p>
            <div className="mt-3 grid grid-cols-1 md:grid-cols-2 gap-2">
              {([
                { key: "one_thread",       label: "One grouped thread",   sub: `All ${pickedContexts.length} contexts in a single conversation. Best for the same message to the same people.` },
                { key: "separate_threads", label: "Separate per context", sub: `Create ${pickedContexts.length} threads — one per record. Best for evidence / payment / per-school follow-up.` },
              ] as { key: SendMode; label: string; sub: string }[]).map((opt) => {
                const active = sendMode === opt.key;
                return (
                  <button
                    key={opt.key}
                    type="button"
                    onClick={() => setSendMode(opt.key)}
                    className={cn(
                      "text-left rounded-lg border px-3 py-2.5 transition-colors",
                      active
                        ? "bg-[var(--color-edify-primary)] border-[var(--color-edify-primary)] text-white"
                        : "bg-white border-[var(--color-edify-border)] hover:bg-[var(--color-edify-soft)]/40",
                    )}
                  >
                    <div className="text-body font-extrabold">{opt.label}</div>
                    <div className={cn("text-[11px] mt-1 leading-snug", active ? "text-white/85" : "muted")}>
                      {opt.sub}
                    </div>
                  </button>
                );
              })}
            </div>
          </div>
        )}
      </section>

      {/* Suggested receivers — appears once at least one context is
          picked. Driven by the suggestion engine (location, ownership,
          partner assignment, category rules). Role gates filter the
          set before display. */}
      {pickedContexts.length > 0 && (receiverSuggestions.primary.length > 0 || receiverSuggestions.optional.length > 0) && (
        <section className="card p-3.5 lg:p-5">
          <div className="flex items-center justify-between gap-3 flex-wrap">
            <div>
              <h3 className="text-body font-extrabold tracking-tight inline-flex items-center gap-1.5">
                <Sparkles size={12} className="text-[var(--color-edify-primary)]" />
                Suggested receivers
              </h3>
              <p className="text-[11px] text-[var(--color-edify-muted)] mt-0.5">
                Based on your selected context, role scope, partner assignment, and category.
              </p>
            </div>
            {receiverSuggestions.primary.length > 0 && (
              <button
                type="button"
                onClick={acceptAllPrimary}
                className="h-8 px-3 rounded-md bg-[var(--color-edify-primary)] hover:bg-[var(--color-edify-dark)] text-white text-[11.5px] font-extrabold"
              >
                Add all primary
              </button>
            )}
          </div>

          {receiverSuggestions.primary.length > 0 && (
            <>
              <div className="mt-3 text-caption uppercase tracking-[0.06em] font-extrabold text-[var(--color-edify-muted)]">Primary</div>
              <ul className="mt-1.5 space-y-1.5">
                {receiverSuggestions.primary.map((s) => (
                  <SuggestionRow
                    key={s.user.userId}
                    suggestion={s}
                    added={!!picked.find((p) => p.userId === s.user.userId)}
                    onAdd={() => acceptSuggestion(s)}
                  />
                ))}
              </ul>
            </>
          )}

          {receiverSuggestions.optional.length > 0 && (
            <>
              <div className="mt-4 text-caption uppercase tracking-[0.06em] font-extrabold text-[var(--color-edify-muted)]">Optional</div>
              <ul className="mt-1.5 space-y-1.5">
                {receiverSuggestions.optional.map((s) => (
                  <SuggestionRow
                    key={s.user.userId}
                    suggestion={s}
                    added={!!picked.find((p) => p.userId === s.user.userId)}
                    onAdd={() => acceptSuggestion(s)}
                  />
                ))}
              </ul>
            </>
          )}
        </section>
      )}

      {/* Subject + body */}
      <section className="card p-3.5 lg:p-5 space-y-3">
        <label className="block">
          <span className="text-body font-extrabold tracking-tight">Subject</span>
          <input
            type="text"
            value={subject}
            onChange={(e) => setSubject(e.target.value.slice(0, 160))}
            placeholder="One line — what's this about?"
            maxLength={160}
            className="mt-1.5 h-10 w-full px-3 rounded-lg border border-[var(--color-edify-border)] bg-white text-[13px] placeholder:text-[var(--color-edify-muted)] focus:outline-none focus:ring-2 focus:ring-[var(--color-edify-primary)]/30"
          />
        </label>
        <label className="block">
          <span className="text-body font-extrabold tracking-tight">Message</span>
          <textarea
            value={body}
            onChange={(e) => setBody(e.target.value.slice(0, 4000))}
            placeholder="Write your message…"
            rows={8}
            maxLength={4000}
            className="mt-1.5 w-full px-3 py-2.5 rounded-lg border border-[var(--color-edify-border)] bg-white text-[13.5px] leading-[1.7] placeholder:text-[var(--color-edify-muted)] focus:outline-none focus:ring-2 focus:ring-[var(--color-edify-primary)]/30 resize-y"
          />
          <span className="text-caption text-[var(--color-edify-muted)] mt-0.5 block tabular text-right">{body.length}/4000</span>
        </label>
      </section>

      {/* Bulk-send preview banner (spec section 16). Renders when the
          user clicks Send on a multi-thread send — they have to
          confirm before N new threads get created. Keeps the form
          state intact; "Back" returns to editing. */}
      {previewing && (
        <section className="card rounded-2xl border-amber-200 bg-amber-50/40 p-4 lg:p-5">
          <div className="flex items-start gap-3">
            <span className="grid place-items-center h-9 w-9 rounded-md bg-amber-100 text-amber-800 shrink-0">
              <AlertTriangle size={15} />
            </span>
            <div className="flex-1 min-w-0">
              <h3 className="text-[13.5px] font-extrabold tracking-tight text-amber-900">
                You're about to create {pickedContexts.length} message threads
              </h3>
              <p className="text-[11.5px] text-amber-900/80 mt-1 leading-snug">
                One thread per selected context — each with its own subject, body, and recipient list. Easier to track per-record, but you'll see {pickedContexts.length} entries in your Sent folder.
              </p>
              <dl className="mt-3 grid grid-cols-1 sm:grid-cols-3 gap-3 text-[11.5px]">
                <div>
                  <dt className="font-extrabold uppercase tracking-[0.06em] text-[10px] text-amber-900/70">Threads</dt>
                  <dd className="font-extrabold text-amber-900 tabular mt-0.5">{pickedContexts.length}</dd>
                </div>
                <div>
                  <dt className="font-extrabold uppercase tracking-[0.06em] text-[10px] text-amber-900/70">Recipients each</dt>
                  <dd className="font-extrabold text-amber-900 tabular mt-0.5">{picked.length}</dd>
                </div>
                <div>
                  <dt className="font-extrabold uppercase tracking-[0.06em] text-[10px] text-amber-900/70">Total messages</dt>
                  <dd className="font-extrabold text-amber-900 tabular mt-0.5">{pickedContexts.length * picked.length}</dd>
                </div>
              </dl>
            </div>
          </div>
        </section>
      )}

      {/* Footer */}
      <footer className="card rounded-2xl p-3 lg:p-4 flex items-center justify-between gap-3 flex-wrap">
        <button
          type="button"
          onClick={() => {
            if (previewing) setPreviewing(false);
            else router.push(backHref);
          }}
          className="h-9 px-3.5 rounded-lg border border-[var(--color-edify-border)] bg-white text-body font-semibold hover:bg-[var(--color-edify-soft)]/40"
        >
          {previewing ? "Back to edit" : "Cancel"}
        </button>
        <div className="flex items-center gap-3 flex-wrap">
          {!previewing && blockingMessage && (
            <span className="inline-flex items-center gap-1.5 text-[11px] font-semibold text-amber-700">
              <AlertTriangle size={12} />
              {blockingMessage}
            </span>
          )}
          <button
            type="submit"
            disabled={!canSubmit}
            className={cn(
              "h-9 px-4 rounded-lg text-white text-body font-extrabold inline-flex items-center gap-1.5 shadow-[0_1px_2px_rgba(15,23,32,0.06)] transition-colors",
              canSubmit
                ? "bg-[var(--color-edify-primary)] hover:bg-[var(--color-edify-dark)]"
                : "bg-[var(--color-edify-muted)] cursor-not-allowed",
            )}
          >
            <Send size={13} />
            {submitting
              ? "Sending…"
              : previewing
                ? `Confirm — send ${pickedContexts.length} threads`
                : willCreateMultipleThreads
                  ? "Review send"
                  : "Send message"}
          </button>
        </div>
      </footer>
    </form>
  );
}

// Small label helper for the context-type chips.
function contextTypeLabel(t: string): string {
  return t
    .split("_")
    .map((w) => w[0].toUpperCase() + w.slice(1))
    .join(" ");
}

// One row inside the Suggested-Receivers card. Shows the avatar +
// name + email + role + a short "why" reason. The Add button stacks
// the user into the To list above; once added the row dims and shows
// "Added".
function SuggestionRow({
  suggestion,
  added,
  onAdd,
}: {
  suggestion: Suggestion;
  added:      boolean;
  onAdd:      () => void;
}) {
  const u = suggestion.user;
  return (
    <li>
      <div className={cn("flex items-center gap-3 rounded-lg border px-3 py-2.5",
        added
          ? "bg-emerald-50/60 border-emerald-200"
          : "bg-white border-[var(--color-edify-divider)]",
      )}>
        <span className="h-8 w-8 rounded-full bg-[var(--color-edify-soft)] text-[var(--color-edify-primary)] grid place-items-center font-extrabold text-[11px] shrink-0">
          {u.initials}
        </span>
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="text-body font-extrabold tracking-tight">{u.name}</span>
            <span className="text-[10px] uppercase tracking-[0.06em] font-extrabold text-[var(--color-edify-muted)]">{u.displayRole}</span>
            <span className="text-caption text-[var(--color-edify-muted)] truncate">{u.email}</span>
          </div>
          <div className="text-[11px] text-[var(--color-edify-muted)] mt-1 leading-snug line-clamp-2">
            {suggestion.reasons.join(" · ")}
          </div>
        </div>
        {added ? (
          <span className="inline-flex items-center gap-1 text-[11px] font-semibold text-emerald-700 shrink-0">
            <CheckCircle2 size={12} /> Added
          </span>
        ) : (
          <button
            type="button"
            onClick={onAdd}
            className="h-8 px-3 rounded-md border border-[var(--color-edify-border)] bg-white hover:bg-[var(--color-edify-soft)]/40 text-[11.5px] font-semibold shrink-0"
          >
            Add
          </button>
        )}
      </div>
    </li>
  );
}
