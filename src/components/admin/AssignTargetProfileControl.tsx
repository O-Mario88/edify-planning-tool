"use client";

// Target profile assignment — Phase 6, the FINAL onboarding gate.
//
// A Program Lead (or CD/HR/Admin) reviews + approves the staff member's FY
// target profile (defaults from role: CCEO 560 / PL 280 visit target). Once
// assigned, the activation engine flips the staff to Active.

import { useState, useTransition } from "react";
import { useRouter } from "next/navigation";
import { Target, CheckCircle2 } from "lucide-react";
import { Modal } from "@/components/ui/Modal";
import { Input } from "@/components/ui/Input";
import { Button } from "@/components/ui/Button";
import { assignTargetProfile } from "@/lib/actions/staff-actions";

export type TargetDefaults = {
  fy: string;
  visitTarget: number;
  trainingTarget?: number;
  ssaTarget?: number;
  clusterMeetingTarget?: number;
  partnerMonitoringTarget?: number;
};

export function AssignTargetProfileControl({
  staffId,
  staffName,
  defaults,
}: {
  staffId: string;
  staffName: string;
  defaults: TargetDefaults;
}) {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [pending, start] = useTransition();
  const [form, setForm] = useState({
    fy: defaults.fy,
    visitTarget: String(defaults.visitTarget),
    trainingTarget: String(defaults.trainingTarget ?? ""),
    ssaTarget: String(defaults.ssaTarget ?? ""),
    clusterMeetingTarget: String(defaults.clusterMeetingTarget ?? ""),
    partnerMonitoringTarget: String(defaults.partnerMonitoringTarget ?? ""),
  });
  const [msg, setMsg] = useState<string | null>(null);

  const num = (v: string) => (v.trim() === "" ? undefined : Number(v));
  function set<K extends keyof typeof form>(k: K, v: string) { setForm((f) => ({ ...f, [k]: v })); }

  function submit() {
    setMsg(null);
    start(async () => {
      const res = await assignTargetProfile(staffId, {
        fy: form.fy,
        visitTarget: Number(form.visitTarget),
        trainingTarget: num(form.trainingTarget),
        ssaTarget: num(form.ssaTarget),
        clusterMeetingTarget: num(form.clusterMeetingTarget),
        partnerMonitoringTarget: num(form.partnerMonitoringTarget),
      });
      if (res.ok) {
        setMsg(res.activated ? `Approved — ${staffName} is now ACTIVE. Onboarding complete.` : "Target profile saved.");
        router.refresh();
        setTimeout(() => setOpen(false), 1200);
      } else {
        setMsg(res.reason === "FORBIDDEN" ? "Only a Program Lead / CD / HR / Admin can approve targets." : `Could not save (${res.reason}).`);
      }
    });
  }

  return (
    <>
      <Button variant="primary" size="sm" Icon={Target} onClick={() => setOpen(true)}>
        Assign targets
      </Button>

      <Modal
        open={open}
        onClose={() => setOpen(false)}
        title={`Target profile — ${staffName}`}
        description="Review + approve the FY target profile. Defaults come from the role (CCEO 560 / PL 280 FY visits). Approving this is the final onboarding step and activates the staff member."
        variant="drawer-right"
        size="md"
        footer={
          <div className="flex items-center justify-between gap-3 w-full">
            <span className="text-[11px] muted truncate">{msg}</span>
            <div className="flex items-center gap-2 shrink-0">
              <Button variant="ghost" size="sm" onClick={() => setOpen(false)} disabled={pending}>Cancel</Button>
              <Button variant="primary" size="sm" onClick={submit} disabled={pending || !form.visitTarget} Icon={CheckCircle2}>
                {pending ? "Approving…" : "Approve & activate"}
              </Button>
            </div>
          </div>
        }
      >
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
          <Input label="Fiscal Year" value={form.fy} onChange={(e) => set("fy", e.target.value)} />
          <Input label="FY visit target" type="number" value={form.visitTarget} onChange={(e) => set("visitTarget", e.target.value)} />
          <Input label="Training target" type="number" value={form.trainingTarget} onChange={(e) => set("trainingTarget", e.target.value)} />
          <Input label="SSA target" type="number" value={form.ssaTarget} onChange={(e) => set("ssaTarget", e.target.value)} />
          <Input label="Cluster meetings" type="number" value={form.clusterMeetingTarget} onChange={(e) => set("clusterMeetingTarget", e.target.value)} />
          <Input label="Partner monitoring" type="number" value={form.partnerMonitoringTarget} onChange={(e) => set("partnerMonitoringTarget", e.target.value)} />
        </div>
      </Modal>
    </>
  );
}
