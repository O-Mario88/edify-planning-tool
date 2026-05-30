"use client";

// PartnerHelpCenter — searchable, categorised help. Six categories
// cover the partner's full workflow (Schedule · Deliver · Prove ·
// Get paid · Standards · Privacy). Each card opens an inline
// detail panel (no nav away) so the partner doesn't lose context.

import { useMemo, useState } from "react";
import {
  CalendarRange, ClipboardCheck, Upload, Wallet, ShieldCheck, Lock,
  Search, ArrowRight, type LucideIcon,
} from "lucide-react";
import { cn } from "@/lib/utils";

type Category = {
  key: string;
  Icon: LucideIcon;
  tone: "primary" | "amber" | "blue" | "emerald" | "violet" | "rose";
  title: string;
  blurb: string;
  articles: { title: string; body: string }[];
};

const CATEGORIES: Category[] = [
  {
    key: "schedule",
    Icon: CalendarRange,
    tone: "primary",
    title: "How to schedule work",
    blurb: "Place assigned activities into a delivery week so your CCEO can monitor.",
    articles: [
      { title: "From assignment to schedule in 3 steps", body: "1. Open Schedule. 2. Pick an unscheduled activity. 3. Choose week + facilitator + duration. Confirm — it lands on your CCEO's monitoring dashboard automatically." },
      { title: "Requesting a date change",       body: "Open the activity, pick 'Request date change', explain why, and submit. Your CCEO will respond in their next sweep (usually same day)." },
      { title: "Marking an activity as delayed",  body: "If you can't deliver as planned, mark Delayed with a reason. The CCEO sees the delay and can reassign if needed — no surprise back-and-forth." },
      { title: "What happens if I don't schedule",body: "After 5 days an assigned activity is auto-flagged on the CCEO's delay alerts. After 10 days it's auto-eligible for reassignment to another partner." },
    ],
  },
  {
    key: "deliver",
    Icon: ClipboardCheck,
    tone: "blue",
    title: "How to deliver in the field",
    blurb: "Use Today / Field Mode on your phone — one activity, the steps, the start button.",
    articles: [
      { title: "Field Mode (mobile)",     body: "Today / Field Mode shows only your current activity with the required evidence checklist. Tap 'Start activity' when you arrive on site." },
      { title: "What 'delivered' means",  body: "An activity moves to Delivered when you tap 'Start activity' and capture the basic facts (school, date, participants). Evidence comes next." },
      { title: "Joint visits with CCEO",  body: "If your CCEO joins, they sign the visit report as a witness. This counts as a stronger evidence chain in M&E verification." },
    ],
  },
  {
    key: "evidence",
    Icon: Upload,
    tone: "amber",
    title: "Evidence requirements",
    blurb: "What you must upload for each activity type to unlock CCEO confirmation.",
    articles: [
      { title: "Partner-led teacher training", body: "Required: training report, signed attendance sheet, training topic, facilitator name, number of teachers, schools represented, SSA area, partner debrief. Optional: pre/post results, photos." },
      { title: "In-School training",            body: "Required: training notes, school confirmation, training topic, participant count, signed attendance, SSA area, agreed next action, follow-up recommendation. Optional: photos." },
      { title: "Follow-Up visit",              body: "Required: visit report, school confirmation, link to previous activity, what changed since support, SSA area, recommendations, agreed next action. Optional: next follow-up date, photos." },
      { title: "Coaching visit",               body: "Required: coaching report, teacher coached, coaching topic, observation notes, agreed action, improvement target, follow-up date, SSA area." },
      { title: "Classroom observation",        body: "Required: observation form, teacher observed, lesson focus, observation score, coaching feedback, next action, follow-up needed." },
      { title: "Resource delivery",            body: "Required: delivery note, school receiving, resource type + quantity, recipient signature, date received, link to school need. Optional: photo where allowed." },
    ],
  },
  {
    key: "payment",
    Icon: Wallet,
    tone: "emerald",
    title: "Payment workflow",
    blurb: "How payment moves from evidence → CCEO → PL → accountant → paid.",
    articles: [
      { title: "The 4 payment gates",       body: "1. Evidence complete (≥ 80% with no critical items missing). 2. CCEO confirms work. 3. PL approves payment. 4. Accountant clears with a payment reference." },
      { title: "Why a payment can be 'On hold'", body: "PL or accountant pauses with a reason (e.g. scope review, duplicate suspicion, evidence concern). Hold is temporary — it resumes once the reason is resolved." },
      { title: "When to expect payment",    body: "Net 14 days from accountant clearance. Most payments clear within 7 days of CCEO confirmation if evidence is complete on submission." },
    ],
  },
  {
    key: "standards",
    Icon: ShieldCheck,
    tone: "violet",
    title: "Reporting standards & code of conduct",
    blurb: "Cadence Edify expects, plus the partner code of conduct.",
    articles: [
      { title: "Reporting cadence",         body: "Weekly update by Monday for the prior week. Monthly impact summary by the last business day. Quarterly performance within 10 business days of quarter close. Special incident report within 48h." },
      { title: "Partner code of conduct",   body: "No undisclosed conflicts of interest. No payment recommendations without evidence. No data shared with non-Edify parties without written consent. Safeguarding incidents reported within 24h." },
      { title: "What counts as a conflict", body: "A facilitator related to a school staff member; a partner team member with a paid role at a school; a previously contracted vendor in the school's chain. Disclose before you deliver." },
    ],
  },
  {
    key: "privacy",
    Icon: Lock,
    tone: "rose",
    title: "Data & privacy rules",
    blurb: "What you can collect, how to store it, what to share.",
    articles: [
      { title: "Photos and minors",         body: "Photos of pupils require written headteacher consent. Faces should not be identifiable unless explicit consent is on file. Default to whiteboards, materials, classroom wide shots, or activity proof." },
      { title: "Sharing partner data",       body: "Aggregate counts are shareable. Individual teacher or pupil identifiers are NOT shareable outside Edify systems. Donors see verified counts + qualitative stories, never raw data." },
      { title: "Storage & retention",        body: "Activity reports + evidence stay in Edify for 7 years. Partners must not retain identifiable data beyond contract end + 90 days." },
    ],
  },
];

const TONE: Record<Category["tone"], { bg: string; text: string; ring: string }> = {
  primary:  { bg: "bg-[var(--color-edify-soft)]", text: "text-[var(--color-edify-primary)]", ring: "ring-[var(--color-edify-divider)]" },
  amber:    { bg: "bg-amber-50",   text: "text-amber-700",   ring: "ring-amber-100"   },
  blue:     { bg: "bg-blue-50",    text: "text-blue-700",    ring: "ring-blue-100"    },
  emerald:  { bg: "bg-emerald-50", text: "text-emerald-700", ring: "ring-emerald-100" },
  violet:   { bg: "bg-violet-50",  text: "text-violet-700",  ring: "ring-violet-100"  },
  rose:     { bg: "bg-rose-50",    text: "text-rose-700",    ring: "ring-rose-100"    },
};

export function PartnerHelpCenter() {
  const [q, setQ] = useState("");
  const [openKey, setOpenKey] = useState<string | null>("schedule");

  const filtered = useMemo(() => {
    if (!q.trim()) return CATEGORIES;
    const needle = q.toLowerCase();
    return CATEGORIES
      .map((c) => ({
        ...c,
        articles: c.articles.filter((a) =>
          a.title.toLowerCase().includes(needle) || a.body.toLowerCase().includes(needle),
        ),
      }))
      .filter((c) => c.articles.length > 0 || c.title.toLowerCase().includes(needle));
  }, [q]);

  return (
    <div className="space-y-4">
      {/* Search */}
      <div className="card p-3.5 flex items-center gap-3">
        <span className="grid place-items-center h-9 w-9 rounded-xl bg-[var(--color-edify-soft)] text-[var(--color-edify-primary)] shrink-0">
          <Search size={15} />
        </span>
        <input
          type="text"
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder="Search how-tos — e.g. 'attendance sheet', 'payment hold', 'safeguarding'"
          className="flex-1 h-9 px-2 text-[13px] bg-transparent focus:outline-none placeholder:text-[var(--color-edify-muted)]"
        />
        {q && (
          <button
            type="button"
            onClick={() => setQ("")}
            className="text-[11.5px] muted hover:text-[var(--color-edify-text)]"
          >
            Clear
          </button>
        )}
      </div>

      {/* Category grid */}
      <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-3">
        {filtered.map((c) => {
          const t = TONE[c.tone];
          const isOpen = openKey === c.key;
          return (
            <article key={c.key} className="card p-3.5 flex flex-col">
              <header className="flex items-start gap-3">
                <span className={cn("grid place-items-center h-10 w-10 rounded-xl shrink-0 ring-4", t.bg, t.text, t.ring)}>
                  <c.Icon size={16} />
                </span>
                <div className="min-w-0 flex-1">
                  <h3 className="text-[13.5px] font-extrabold tracking-tight">{c.title}</h3>
                  <p className="text-[11.5px] muted leading-snug mt-0.5">{c.blurb}</p>
                </div>
              </header>
              {isOpen && (
                <ul className="mt-3 space-y-2.5">
                  {c.articles.map((a) => (
                    <li key={a.title} className="rounded-lg border border-[var(--color-edify-divider)] p-2.5">
                      <div className="text-[12px] font-extrabold tracking-tight">{a.title}</div>
                      <p className="text-[11px] muted leading-snug mt-1">{a.body}</p>
                    </li>
                  ))}
                </ul>
              )}
              <div className="mt-auto pt-3">
                <button
                  type="button"
                  onClick={() => setOpenKey(isOpen ? null : c.key)}
                  className="inline-flex items-center gap-1 text-[11.5px] font-semibold text-[var(--color-edify-primary)] hover:underline"
                >
                  {isOpen ? "Hide articles" : `Open ${c.articles.length} article${c.articles.length === 1 ? "" : "s"}`}
                  <ArrowRight size={11} />
                </button>
              </div>
            </article>
          );
        })}
      </div>

      {/* Contact CCEO fallback */}
      <section className="card p-3.5 flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3">
        <div>
          <h3 className="text-[13.5px] font-extrabold tracking-tight">Can't find what you need?</h3>
          <p className="text-[11.5px] muted mt-0.5">Send a question to your Edify focal CCEO — they'll respond in their next sweep.</p>
        </div>
        <button
          type="button"
          className="inline-flex items-center gap-1.5 h-9 px-4 rounded-xl bg-[var(--color-edify-primary)] text-white text-[12px] font-extrabold hover:bg-[var(--color-edify-dark)]"
        >
          Ask your CCEO <ArrowRight size={12} />
        </button>
      </section>
    </div>
  );
}
