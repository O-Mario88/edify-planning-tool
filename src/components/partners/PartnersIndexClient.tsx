"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import {
  Handshake,
  Plus,
  X,
  Trash2,
  ShieldCheck,
  CheckCircle2,
  AlertTriangle,
  GraduationCap,
} from "lucide-react";
import type { EdifyRole } from "@/lib/auth-public";
import {
  SEED_PARTNER_TRAINS_ON,
  addPartner,
  canAddPartner,
  formatRelative,
  listPartners,
  partnerEditorRolesLabel,
  removePartner,
  subscribePartners,
  type AddedPartner,
} from "@/lib/partners-store";
import { partnerTargetPerformance, type PartnerTargetRow } from "@/lib/team-targets-mock";
import { Pill, type PillTone } from "@/components/ui/Pill";
import { EmptyState } from "@/components/ui/EmptyState";

const CERT_TONE: Record<PartnerTargetRow["certificationStatus"], PillTone> = {
  "Certified":     "success",
  "Pending":       "warning",
  "Not Certified": "danger",
};

const RISK_TONE: Record<PartnerTargetRow["risk"], PillTone> = {
  Low:      "success",
  Medium:   "warning",
  High:     "danger",
  Critical: "amber",
};

export function PartnersIndexClient({ role, userName }: { role: EdifyRole; userName: string }) {
  const [added, setAdded] = useState<AddedPartner[]>([]);
  const [openForm, setOpenForm] = useState(false);
  const canAdd = canAddPartner(role);

  // Hydrate and subscribe to the client-side partner store. Migrate to
  // useSyncExternalStore during the React-19 sweep.
  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setAdded(listPartners());
    return subscribePartners(() => setAdded(listPartners()));
  }, []);

  return (
    <>
      {/* Header strip — count + role-gated CTA */}
      <header className="flex items-end justify-between gap-3 flex-wrap pb-2">
        <div>
          <h2 className="text-[13px] font-extrabold tracking-tight">All Partners</h2>
          <p className="text-[11.5px] muted mt-0.5">
            {partnerTargetPerformance.length + added.length} partners ·{" "}
            {added.length} added by your team · Partners can only be added by {partnerEditorRolesLabel()}.
          </p>
        </div>
        {canAdd ? (
          <button
            type="button"
            onClick={() => setOpenForm(true)}
            className="inline-flex items-center gap-1.5 h-9 px-3.5 rounded-lg bg-[var(--color-edify-primary)] text-white text-[12px] font-semibold hover:opacity-95"
          >
            <Plus size={13} /> Add Partner
          </button>
        ) : (
          <span className="inline-flex items-center gap-1.5 h-9 px-3 rounded-lg bg-[var(--color-edify-soft)]/60 text-secondary text-[11.5px] font-semibold">
            <ShieldCheck size={13} /> Read-only for your role
          </span>
        )}
      </header>

      {/* Recently added (top) — show first so contributors see their
          writes. When a user *can* add but hasn't yet, surface a
          welcoming first-run empty state instead of hiding the section
          entirely — that's the moment they understand what's possible. */}
      {added.length === 0 && canAdd && (
        <EmptyState
          Icon={Plus}
          tone="violet"
          title="No partners added by your team yet"
          body="Onboard delivery partners with the curriculum they're certified to train on. Everyone with access to Partners can read your additions."
          action={
            <button
              type="button"
              onClick={() => setOpenForm(true)}
              className="inline-flex items-center gap-1.5 h-9 px-4 rounded-lg bg-[var(--color-edify-primary)] text-white text-body font-semibold hover:opacity-95"
            >
              <Plus size={13} /> Add the first partner
            </button>
          }
        />
      )}
      {added.length > 0 && (
        <section className="card rounded-2xl overflow-hidden">
          <header className="px-4 py-3 border-b border-[var(--color-edify-divider)] flex items-center justify-between">
            <h3 className="text-body font-extrabold tracking-tight">Recently Added</h3>
            <span className="text-[11px] muted">{added.length} record{added.length === 1 ? "" : "s"}</span>
          </header>
          <ul className="divide-y divide-[var(--color-edify-divider)]">
            {added.map((p) => (
              <li key={p.id} className="px-4 py-3.5 flex items-start gap-3 hover:bg-[var(--color-edify-soft)]/40">
                <span className="h-10 w-10 rounded-xl bg-violet-100 text-violet-700 grid place-items-center shrink-0">
                  <Handshake size={16} />
                </span>
                <div className="flex-1 min-w-0">
                  <div className="text-[13px] font-extrabold tracking-tight truncate">{p.name}</div>
                  <div className="text-[11.5px] muted truncate">{p.region}</div>
                  {p.trainsOn.length > 0 && (
                    <div className="mt-1.5 flex items-center gap-1 flex-wrap">
                      <GraduationCap size={11} className="text-muted" />
                      {p.trainsOn.map((t) => (
                        <span key={t} className="px-2 h-[20px] inline-flex items-center rounded-full bg-violet-50 text-violet-700 text-caption font-semibold border border-violet-100">
                          {t}
                        </span>
                      ))}
                    </div>
                  )}
                  {p.notes && <div className="text-[11px] text-muted mt-1 line-clamp-2">{p.notes}</div>}
                  <div className="text-caption text-muted mt-1">
                    Added by {p.addedByName} · {formatRelative(p.addedAt)}
                  </div>
                </div>
                {p.addedByName === userName && p.addedByRole === role && (
                  <button
                    type="button"
                    onClick={() => {
                      if (confirm(`Remove "${p.name}"?`)) removePartner(p.id);
                    }}
                    aria-label={`Remove ${p.name}`}
                    className="grid place-items-center h-8 w-8 rounded-md text-[#b3bcc5] hover:text-[#b42318] hover:bg-rose-50 shrink-0 self-center"
                  >
                    <Trash2 size={14} />
                  </button>
                )}
              </li>
            ))}
          </ul>
        </section>
      )}

      {/* Seed delivery partners — operational rows from team-targets-mock,
          enriched with the topics they train on so the read matches the
          shape of newly added partners. */}
      <section className="card rounded-2xl overflow-hidden">
        <header className="px-4 py-3 border-b border-[var(--color-edify-divider)]">
          <h3 className="text-body font-extrabold tracking-tight">Established Delivery Partners</h3>
        </header>
        <ul className="divide-y divide-[var(--color-edify-divider)]">
          {partnerTargetPerformance.map((p) => {
            const trainsOn = SEED_PARTNER_TRAINS_ON[p.partnerId] ?? [];
            return (
              <li key={p.partnerId} className="px-4 py-3.5 hover:bg-[var(--color-edify-soft)]/40">
                <Link href={`/partners/${p.partnerId}`} className="flex items-start gap-3">
                  <span className="h-10 w-10 rounded-xl bg-[var(--color-edify-soft)]/80 text-[var(--color-edify-primary)] grid place-items-center shrink-0">
                    <Handshake size={16} />
                  </span>
                  <div className="flex-1 min-w-0">
                    <div className="flex items-baseline justify-between gap-2">
                      <div className="text-[13px] font-extrabold tracking-tight truncate">{p.partner}</div>
                      <div className="text-[12px] font-extrabold tabular shrink-0">{p.achievementPercent}%</div>
                    </div>
                    <div className="text-[11.5px] muted truncate">
                      {p.region} · {p.assignedActivities} assigned · {p.completedActivities} completed · {p.validVisits} valid visits
                    </div>
                    {trainsOn.length > 0 && (
                      <div className="mt-1.5 flex items-center gap-1 flex-wrap">
                        <GraduationCap size={11} className="text-muted" />
                        {trainsOn.map((t) => (
                          <span key={t} className="px-2 h-[20px] inline-flex items-center rounded-full bg-violet-50 text-violet-700 text-caption font-semibold border border-violet-100">
                            {t}
                          </span>
                        ))}
                      </div>
                    )}
                    <div className="mt-1.5 flex items-center gap-1 flex-wrap">
                      <Pill tone={CERT_TONE[p.certificationStatus]} size="xs" icon={CheckCircle2}>
                        {p.certificationStatus}
                      </Pill>
                      <Pill tone={RISK_TONE[p.risk]} size="xs" icon={AlertTriangle}>
                        {p.risk} risk
                      </Pill>
                    </div>
                  </div>
                </Link>
              </li>
            );
          })}
        </ul>
      </section>

      {openForm && (
        <AddPartnerDialog role={role} userName={userName} onClose={() => setOpenForm(false)} />
      )}
    </>
  );
}

// ────────── Add Partner dialog ──────────

function AddPartnerDialog({
  role,
  userName,
  onClose,
}: {
  role: EdifyRole;
  userName: string;
  onClose: () => void;
}) {
  const [name, setName]       = useState("");
  const [region, setRegion]   = useState("Central");
  const [trainsOn, setTrainsOn] = useState("");
  const [notes, setNotes]     = useState("");
  const [error, setError]     = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement | null>(null);

  useEffect(() => {
    function onKey(e: KeyboardEvent) { if (e.key === "Escape") onClose(); }
    document.addEventListener("keydown", onKey);
    inputRef.current?.focus();
    return () => document.removeEventListener("keydown", onKey);
  }, [onClose]);

  const topics = useMemo(
    () => trainsOn.split(",").map((t) => t.trim()).filter(Boolean),
    [trainsOn],
  );

  const disabled = !name.trim() || topics.length === 0;

  function submit() {
    setError(null);
    if (disabled) {
      setError("Partner name and at least one training topic are required.");
      return;
    }
    addPartner({
      name:        name.trim(),
      region:      region.trim() || "Unassigned",
      trainsOn:    topics,
      notes:       notes.trim(),
      addedByName: userName,
      addedByRole: role,
    });
    onClose();
  }

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label="Add Partner"
      className="fixed inset-0 z-50 flex items-start sm:items-center justify-center p-4 bg-black/40"
      onClick={onClose}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        className="w-full max-w-[520px] rounded-2xl bg-white shadow-[0_24px_60px_-20px_rgba(15,23,32,0.35)] overflow-hidden"
      >
        <header className="flex items-center justify-between gap-3 px-5 py-4 border-b border-[var(--color-edify-divider)]">
          <div>
            <div className="text-body-lg font-extrabold tracking-tight">Add a Partner</div>
            <div className="text-[11px] muted mt-0.5">
              Visible to everyone with access to Partners.
            </div>
          </div>
          <button
            type="button"
            aria-label="Close"
            onClick={onClose}
            className="grid place-items-center h-8 w-8 rounded-md text-[#b3bcc5] hover:text-secondary hover:bg-[#f4f6f8]"
          >
            <X size={16} />
          </button>
        </header>

        <div className="px-5 py-4 space-y-3.5">
          <label className="block">
            <div className="text-[11.5px] font-semibold muted mb-1">Partner Name</div>
            <input
              ref={inputRef}
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="e.g. Right to Play"
              className="w-full h-10 px-3 rounded-lg border border-[var(--color-edify-border)] text-[13px] focus:outline-none focus:ring-2 focus:ring-[var(--color-edify-primary)]/30"
            />
          </label>

          <label className="block">
            <div className="text-[11.5px] font-semibold muted mb-1">Region</div>
            <select
              value={region}
              onChange={(e) => setRegion(e.target.value)}
              className="w-full h-10 px-3 rounded-lg border border-[var(--color-edify-border)] text-[13px] bg-white focus:outline-none focus:ring-2 focus:ring-[var(--color-edify-primary)]/30"
            >
              {["North", "South", "East", "West", "Central", "All Regions"].map((r) => (
                <option key={r} value={r}>{r}</option>
              ))}
            </select>
          </label>

          <label className="block">
            <div className="text-[11.5px] font-semibold muted mb-1">Trains On</div>
            <input
              type="text"
              value={trainsOn}
              onChange={(e) => setTrainsOn(e.target.value)}
              placeholder="Comma-separated topics, e.g. Christ-like Behavior, Child Protection"
              className="w-full h-10 px-3 rounded-lg border border-[var(--color-edify-border)] text-[13px] focus:outline-none focus:ring-2 focus:ring-[var(--color-edify-primary)]/30"
            />
            {topics.length > 0 && (
              <div className="mt-2 flex items-center gap-1 flex-wrap">
                {topics.map((t) => (
                  <span key={t} className="px-2 h-[22px] inline-flex items-center rounded-full bg-violet-50 text-violet-700 text-[11px] font-semibold border border-violet-100">
                    {t}
                  </span>
                ))}
              </div>
            )}
          </label>

          <label className="block">
            <div className="text-[11.5px] font-semibold muted mb-1">Notes (Optional)</div>
            <textarea
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              rows={3}
              placeholder="Scope of work, MOU expiry, lead contact, etc."
              className="w-full px-3 py-2 rounded-lg border border-[var(--color-edify-border)] text-[13px] focus:outline-none focus:ring-2 focus:ring-[var(--color-edify-primary)]/30"
            />
          </label>

          {error && (
            <div className="text-[11.5px] text-rose-700 bg-rose-50 border border-rose-200 rounded-md px-3 py-2">
              {error}
            </div>
          )}
        </div>

        <footer className="flex items-center justify-end gap-2 px-5 py-3 border-t border-[var(--color-edify-divider)] bg-[var(--color-edify-soft)]/30">
          <button
            type="button"
            onClick={onClose}
            className="h-9 px-3 rounded-lg text-body font-semibold text-secondary hover:bg-white"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={submit}
            disabled={disabled}
            className="h-9 px-4 rounded-lg bg-[var(--color-edify-primary)] text-white text-body font-semibold disabled:opacity-50"
          >
            Add partner
          </button>
        </footer>
      </div>
    </div>
  );
}
