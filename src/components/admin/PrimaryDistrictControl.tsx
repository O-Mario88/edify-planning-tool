"use client";

// Primary-district setup — Phase 5 of onboarding.
//
// The home/base district (no accommodation); every other assigned district
// becomes secondary (travel burden). Setting it clears the primary-district
// activation gate and unblocks budget calculation for the staff member.

import { useMemo, useState, useTransition } from "react";
import { useRouter } from "next/navigation";
import { MapPin, CheckCircle2 } from "lucide-react";
import { Modal } from "@/components/ui/Modal";
import { Select } from "@/components/ui/Select";
import { Button } from "@/components/ui/Button";
import { districtsInRegion, type UgandaRegion } from "@/lib/geography";
import { setPrimaryDistrict } from "@/lib/actions/staff-actions";

export function PrimaryDistrictControl({
  staffId,
  staffName,
  region,
  defaultDistrict,
}: {
  staffId: string;
  staffName: string;
  region?: string;
  defaultDistrict?: string;
}) {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [pending, start] = useTransition();
  const [district, setDistrict] = useState(defaultDistrict ?? "");
  const [msg, setMsg] = useState<string | null>(null);

  const options = useMemo(
    () => (region ? districtsInRegion(region as UgandaRegion).map((d) => ({ value: d, label: d })) : []),
    [region],
  );

  function submit() {
    if (!district) return;
    setMsg(null);
    start(async () => {
      const res = await setPrimaryDistrict(staffId, district);
      if (res.ok) {
        setMsg(`Primary district set to ${district}. Other districts are now secondary; budget can be calculated.`);
        router.refresh();
        setTimeout(() => setOpen(false), 1100);
      } else {
        setMsg(res.reason === "FORBIDDEN" ? "Only CD / HR / Admin (or the staff) can set this." : `Could not set (${res.reason}).`);
      }
    });
  }

  return (
    <>
      <Button variant="secondary" size="sm" Icon={MapPin} onClick={() => setOpen(true)}>
        Set primary district
      </Button>

      <Modal
        open={open}
        onClose={() => setOpen(false)}
        title={`Primary district — ${staffName}`}
        description="The home/base district where the staff member needs no accommodation. Every other assigned district becomes secondary (travel burden). Required before budget can be calculated."
        variant="drawer-right"
        size="md"
        footer={
          <div className="flex items-center justify-between gap-3 w-full">
            <span className="text-[11px] muted truncate">{msg}</span>
            <div className="flex items-center gap-2 shrink-0">
              <Button variant="ghost" size="sm" onClick={() => setOpen(false)} disabled={pending}>Cancel</Button>
              <Button variant="primary" size="sm" onClick={submit} disabled={pending || !district} Icon={CheckCircle2}>
                {pending ? "Saving…" : "Set primary district"}
              </Button>
            </div>
          </div>
        }
      >
        <Select
          label="Primary (home) district"
          placeholder={region ? "Select district" : "Staff has no region set"}
          value={district}
          options={options}
          disabled={!region}
          helper="Primary = no accommodation. All other assigned districts auto-classify as secondary."
          onChange={(e) => setDistrict(e.target.value)}
        />
      </Modal>
    </>
  );
}
