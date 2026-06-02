"use client";

// Per-school partner delegation control (on My Portfolio).
//
// Shows active partner delegations as badges (each cancellable) and an "Assign
// partner" action. Assigning delegates execution only — the school never leaves
// the owner's portfolio and ownership is never transferred.

import { useState, useTransition } from "react";
import { useRouter } from "next/navigation";
import { Handshake, X, Plus } from "lucide-react";
import { Modal } from "@/components/ui/Modal";
import { Input } from "@/components/ui/Input";
import { Select } from "@/components/ui/Select";
import { Button } from "@/components/ui/Button";
import { assignPartnerToSchool, cancelPartnerAssignment } from "@/lib/actions/portfolio-actions";

export type ActiveDelegation = { id: string; partnerName: string; interventionArea?: string };

export function SchoolPartnerControl({
  schoolId, schoolName, delegations, partnerOptions, interventionAreas,
}: {
  schoolId: string;
  schoolName: string;
  delegations: ActiveDelegation[];
  partnerOptions: string[];
  interventionAreas: string[];
}) {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [pending, start] = useTransition();
  const [partnerName, setPartnerName] = useState("");
  const [area, setArea] = useState("");
  const [note, setNote] = useState("");
  const [msg, setMsg] = useState<string | null>(null);

  function submit() {
    if (!partnerName.trim()) { setMsg("Enter a partner name."); return; }
    setMsg(null);
    start(async () => {
      const res = await assignPartnerToSchool({ schoolId, partnerName, interventionArea: area || undefined, note: note || undefined });
      if (res.ok) {
        setPartnerName(""); setArea(""); setNote("");
        setOpen(false);
        router.refresh();
      } else if (res.reason === "FORBIDDEN") {
        setMsg("Only the account owner (or their lead) can delegate this school.");
      } else if (res.reason === "INVALID_INPUT") {
        setMsg("Enter a partner name.");
      } else {
        setMsg("That school could not be found.");
      }
    });
  }

  function cancel(id: string) {
    start(async () => {
      await cancelPartnerAssignment(id);
      router.refresh();
    });
  }

  return (
    <>
      <div className="flex flex-wrap items-center gap-1">
        {delegations.map((d) => (
          <span key={d.id} className="inline-flex items-center gap-1 px-1.5 py-[2px] rounded-md text-[10px] font-extrabold bg-sky-100 text-sky-700">
            <Handshake size={10} /> {d.partnerName}{d.interventionArea ? ` · ${d.interventionArea}` : ""}
            <button type="button" aria-label={`Cancel ${d.partnerName}`} onClick={() => cancel(d.id)}
              disabled={pending} className="ml-0.5 hover:text-sky-900">
              <X size={10} />
            </button>
          </span>
        ))}
        <button type="button" onClick={() => setOpen(true)}
          className="inline-flex items-center gap-1 px-1.5 py-[2px] rounded-md text-[10px] font-extrabold border border-dashed border-[var(--color-edify-border)] text-[var(--color-edify-muted)] hover:text-[var(--color-edify-text)]">
          <Plus size={10} /> Assign partner
        </button>
      </div>

      <Modal
        open={open}
        onClose={() => setOpen(false)}
        title="Assign a partner"
        description={`Delegate delivery at ${schoolName}. This does not transfer ownership — the school stays in your portfolio.`}
        variant="drawer-right"
        size="sm"
        footer={
          <div className="flex items-center justify-between gap-3 w-full">
            <span className="text-[11px] muted truncate">{msg}</span>
            <div className="flex items-center gap-2 shrink-0">
              <Button variant="ghost" size="sm" onClick={() => setOpen(false)} disabled={pending}>Cancel</Button>
              <Button variant="primary" size="sm" Icon={Handshake} onClick={submit} disabled={pending}>
                {pending ? "Assigning…" : "Assign partner"}
              </Button>
            </div>
          </div>
        }
      >
        <div className="space-y-3">
          <div className="flex flex-col gap-1">
            <label htmlFor="partner-name" className="text-[11.5px] font-semibold text-[var(--color-edify-text)]">Partner *</label>
            <input id="partner-name" list="partner-suggestions" value={partnerName} placeholder="Hope Education Partners"
              onChange={(e) => setPartnerName(e.target.value)}
              className="h-10 px-3 text-[13px] rounded-lg bg-white border border-[var(--color-edify-border)] outline-none focus:outline-2 focus:outline-[var(--color-edify-primary)]" />
            <datalist id="partner-suggestions">
              {partnerOptions.map((p) => <option key={p} value={p} />)}
            </datalist>
          </div>
          <Select label="Intervention area (optional)" placeholder="Any / not specified" value={area}
            options={interventionAreas.map((a) => ({ value: a, label: a }))}
            onChange={(e) => setArea(e.target.value)} />
          <Input label="Note (optional)" placeholder="What the partner will deliver" value={note}
            onChange={(e) => setNote(e.target.value)} />
          <p className="text-[10.5px] muted">
            The partner delivers on your behalf. You keep ownership, planning, and reporting for this school.
          </p>
        </div>
      </Modal>
    </>
  );
}
