"use client";

// AssignToPartnerDrawer — the slim, partner-only assignment drawer.
//
// Exactly four things, per the operating model: the partner picks the date
// themselves later, so this drawer NEVER asks for a month/week/date.
//
//   1. Activity            — what is being assigned (visit / training)
//   2. Partner             — the certified partner who will deliver it
//   3. Intervention        — SSA-auto (the school's weakest SSA area, read-only)
//   4. Estimated cost      — CD catalogue (partner lump sum, read-only)
//
// Backend-driven: submit POSTs /api/activities with deliveryType=partner +
// assignedPartnerId and NO date → the activity persists as
// status=assigned_to_partner. It lands on the partner's scheduling dashboard
// and in the assigner's "Assigned to Partner" monitoring queue. The partner
// later schedules the exact date (which returns it to the monitoring queue).

import { useEffect, useMemo, useState } from "react";
import { Handshake, X, Wallet, Sparkles, GraduationCap, Footprints, Building2 } from "lucide-react";
import { Modal } from "@/components/ui/Modal";
import { Select } from "@/components/ui/Select";
import { Button } from "@/components/ui/Button";

// Edify FY quarters: Q1 Jul–Sep, Q2 Oct–Dec, Q3 Jan–Mar, Q4 Apr–Jun.
const quarterFor = (m: number) => (m >= 7 && m <= 9 ? "Q1" : m >= 10 ? "Q2" : m <= 3 ? "Q3" : "Q4");
const ugx = (n: number) => `UGX ${Math.round(n).toLocaleString()}`;

// Activity options per school type. `be` = the real backend ActivityType;
// `isTraining` toggles the icon + the (unused-here) participant framing.
type ActOption = { v: string; l: string; be: string; isTraining: boolean };
const CLIENT_ACTS: ActOption[] = [
  { v: "school_visit", l: "School visit", be: "school_visit", isTraining: false },
  { v: "school_improvement_training", l: "School Improvement Training", be: "school_improvement_training", isTraining: true },
  { v: "follow_up_visit", l: "Follow-up visit", be: "follow_up_visit", isTraining: false },
  { v: "coaching_visit", l: "Coaching visit", be: "coaching_visit", isTraining: false },
];
const CORE_ACTS: ActOption[] = [
  { v: "core_visit", l: "Core visit", be: "core_visit", isTraining: false },
  { v: "core_training", l: "Core training", be: "core_training", isTraining: true },
];

export type AssignToPartnerContext = {
  /** Target school. `type` picks the activity menu (client vs core). */
  school: { id: string; name: string; type?: "client" | "core" };
  /** Header subtitle, e.g. "Kitgum · Hope Primary · CCEO Acan". */
  locationLine?: string;
  /** SSA-auto intervention — the school's weakest SSA area label. */
  intervention?: string;
  /** Score for the weakest area (0–10), shown alongside the intervention. */
  interventionScore?: number;
  /** Backend ActivityType to preselect (matches an option's `be`). */
  defaultActivityType?: string;
};

type BePartnerLite = { id: string; name: string };

export function AssignToPartnerDrawer({
  open, context, onClose, onAssigned,
}: {
  open: boolean;
  context: AssignToPartnerContext | null;
  onClose: () => void;
  /** Fired after a successful backend write so the parent can dismiss the row. */
  onAssigned: (summary: { partnerName: string; activityLabel: string }) => void;
}) {
  const acts = context?.school.type === "core" ? CORE_ACTS : CLIENT_ACTS;
  const [activity, setActivity] = useState(acts[0].v);
  const [partners, setPartners] = useState<BePartnerLite[]>([]);
  const [partnerId, setPartnerId] = useState<string>("");
  const [rates, setRates] = useState<Record<string, number>>({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Re-seed on open. Preselect the recommended activity when given.
  useEffect(() => {
    if (!open || !context) return;
    const menu = context.school.type === "core" ? CORE_ACTS : CLIENT_ACTS;
    const preset = menu.find((a) => a.be === context.defaultActivityType)?.v ?? menu[0].v;
    setActivity(preset);
    setError(null);
  }, [open, context]);

  // CD rate card → partner lump-sum estimate.
  useEffect(() => {
    if (!open) return;
    fetch("/api/budget/cost-settings", { credentials: "include" })
      .then((r) => r.json())
      .then((j) => {
        if (j.live) { const m: Record<string, number> = {}; for (const s of j.settings) m[s.key] = s.unitCost; setRates(m); }
      })
      .catch(() => undefined);
  }, [open]);

  // Certified partner directory.
  useEffect(() => {
    if (!open) return;
    fetch("/api/partners", { credentials: "include" })
      .then((r) => r.json())
      .then((j) => {
        if (j.live && Array.isArray(j.partners)) {
          const list = j.partners.map((p: { id: string; name: string }) => ({ id: p.id, name: p.name }));
          setPartners(list);
          setPartnerId((cur) => cur || list[0]?.id || "");
        }
      })
      .catch(() => undefined);
  }, [open]);

  const selected = acts.find((a) => a.v === activity) ?? acts[0];
  const Icon = selected.isTraining ? GraduationCap : Footprints;

  // Same partner costing the budget engine applies: a single CD lump sum.
  const estimate = useMemo(() => {
    const amount = rates["partner_visit_lump_sum"];
    return amount != null ? { amount, line: "Partner lump sum" } : null;
  }, [rates]);

  if (!context) return null;
  const partnerName = partners.find((p) => p.id === partnerId)?.name ?? "partner";

  async function submit() {
    if (!context || !partnerId) return;
    setBusy(true); setError(null);
    const month = new Date().getMonth() + 1;
    try {
      const res = await fetch("/api/activities", {
        method: "POST", credentials: "include", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          activityType: selected.be,
          schoolId: context.school.id,
          fy: "2026",
          quarter: quarterFor(month),
          deliveryType: "partner",
          assignedPartnerId: partnerId,
          // No date — the partner schedules the exact day from their dashboard.
        }),
      });
      const j = await res.json();
      if (j.live) {
        onAssigned({ partnerName, activityLabel: selected.l });
      } else {
        setError(j.error || "The backend rejected this (scope or partner).");
      }
    } catch {
      setError("Could not reach the server.");
    }
    setBusy(false);
  }

  return (
    <Modal
      open={open}
      onClose={onClose}
      title="Assign to partner"
      description={`${context.school.name}${context.locationLine ? ` · ${context.locationLine}` : ""}`}
      size="md"
      variant="sheet"
      footer={
        <div className="flex items-center justify-end gap-2 w-full">
          <Button variant="ghost" size="sm" onClick={onClose}>Cancel</Button>
          <Button
            size="sm"
            Icon={Handshake}
            disabled={busy || !partnerId}
            onClick={submit}
          >
            {busy ? "Assigning…" : !partnerId ? "Choose a partner" : `Assign to ${partnerName}`}
          </Button>
        </div>
      }
    >
      <div className="space-y-4">
        {/* Activity info card */}
        <section className="rounded-lg border border-[var(--color-edify-border)] bg-[var(--color-edify-soft)]/40 p-3 flex items-start gap-2.5">
          <span className="grid place-items-center h-8 w-8 rounded-md bg-white text-[var(--color-edify-primary)] shrink-0 border border-[var(--color-edify-border)]">
            <Icon size={14} />
          </span>
          <div className="min-w-0">
            <div className="text-[13px] font-extrabold tracking-tight">{selected.l}</div>
            <div className="text-[11.5px] muted leading-tight inline-flex items-center gap-1">
              <Building2 size={10} /> {context.school.name}
            </div>
            <div className="text-[11px] muted leading-snug mt-1">
              The partner picks the delivery date from their dashboard — no month or week is set here.
            </div>
          </div>
        </section>

        {/* 1. Activity */}
        <Select
          label="Activity"
          value={activity}
          onChange={(e) => setActivity(e.target.value)}
          options={acts.map((a) => ({ value: a.v, label: a.l }))}
          helper="What the partner will deliver at this school."
        />

        {/* 2. Partner */}
        {partners.length === 0 ? (
          <div>
            <label className="block text-[10.5px] font-bold uppercase tracking-wide muted mb-1">Partner</label>
            <div className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-[11.5px] text-amber-700 font-semibold">
              No certified partners available to assign.
            </div>
          </div>
        ) : (
          <Select
            label="Partner"
            value={partnerId}
            onChange={(e) => setPartnerId(e.target.value)}
            options={partners.map((p) => ({ value: p.id, label: p.name }))}
            helper="Certified partners only. They are notified immediately."
          />
        )}

        {/* 3. Intervention — SSA auto (read-only) */}
        <div>
          <label className="block text-[10.5px] font-bold uppercase tracking-wide muted mb-1">Intervention</label>
          <div className="rounded-lg border border-[var(--color-edify-border)] bg-white px-3 py-2.5 flex items-center justify-between gap-2">
            <span className="text-[12.5px] font-extrabold text-[var(--color-edify-text)]">
              {context.intervention ?? "SSA pending — generic focus"}
              {context.intervention && context.interventionScore != null && (
                <span className="muted font-semibold"> · {context.interventionScore}/10</span>
              )}
            </span>
            <span className="inline-flex items-center gap-1 rounded-full bg-[var(--color-edify-soft)] text-[var(--color-edify-primary)] px-2 py-0.5 text-[10px] font-bold border border-[var(--color-edify-border)] shrink-0">
              <Sparkles size={9} /> SSA auto
            </span>
          </div>
          <p className="text-[10.5px] muted mt-1">Set automatically from the school&apos;s weakest SSA area — staff cannot edit it.</p>
        </div>

        {/* 4. Estimated cost — CD catalogue (read-only) */}
        <section className="rounded-lg border border-emerald-200 bg-emerald-50/60 p-3 space-y-1.5">
          <header className="inline-flex items-center gap-1.5">
            <Wallet size={12} className="text-emerald-700" />
            <span className="text-[11px] uppercase tracking-wider font-extrabold text-emerald-700">Estimated cost</span>
          </header>
          {estimate ? (
            <>
              <div className="flex items-baseline justify-between">
                <span className="text-[11.5px] muted">{estimate.line}</span>
                <span className="text-body-lg font-extrabold tabular text-emerald-700">{ugx(estimate.amount)}</span>
              </div>
              <p className="text-caption muted leading-snug pt-1">
                <Sparkles size={9} className="inline -mt-0.5 mr-1" />
                Rate set by the Country Director catalogue. Added to the fund request automatically.
              </p>
            </>
          ) : (
            <p className="text-[11px] muted">Loading the CD catalogue rate…</p>
          )}
        </section>

        {error && (
          <div className="rounded-md border border-rose-200 bg-rose-50 px-3 py-2 text-[12px] text-rose-700 inline-flex items-start gap-1.5">
            <X size={12} className="mt-0.5 shrink-0" />
            {error}
          </div>
        )}
      </div>
    </Modal>
  );
}
