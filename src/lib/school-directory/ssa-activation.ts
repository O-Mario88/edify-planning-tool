// SSA activation — the tracked record created when a clustered school's SSA is
// set in motion via one of the three methods (SIT, partner, or staff/self),
// before IA uploads the actual SSA. This makes SSA activation a real, persisted
// step (not an in-session dismiss): the directory / School 360 / planning all
// read it, and it clears once the SSA is uploaded.

export type SsaActivationMethod = "sit" | "partner" | "self";

export const SSA_METHOD_LABEL: Record<SsaActivationMethod, string> = {
  sit: "SIT scheduled",
  partner: "Assigned to partner",
  self: "Staff-scheduled",
};

export type SSAActivation = {
  id: string;
  schoolId: string;
  method: SsaActivationMethod;
  assignedPartnerId?: string;
  assignedPartnerName?: string;
  scheduledDate?: string;
  createdBy: string;
  createdByRole: string;
  createdAt: string;
  active: boolean;
};

export const ssaActivations: SSAActivation[] = [];
let seq = 0;

export function activateSsa(
  schoolId: string,
  method: SsaActivationMethod,
  actor: { name: string; role: string },
  opts: { partnerId?: string; partnerName?: string; date?: string } = {},
): SSAActivation {
  // One active activation per school — supersede any prior.
  for (const a of ssaActivations) if (a.schoolId === schoolId && a.active) a.active = false;
  seq += 1;
  const rec: SSAActivation = {
    id: `SSAA-${String(seq).padStart(4, "0")}`,
    schoolId,
    method,
    assignedPartnerId: opts.partnerId,
    assignedPartnerName: opts.partnerName,
    scheduledDate: opts.date,
    createdBy: actor.name,
    createdByRole: actor.role,
    createdAt: new Date().toISOString(),
    active: true,
  };
  ssaActivations.unshift(rec);
  return rec;
}

/** The active SSA activation for a school, if any. */
export function ssaActivationFor(schoolId: string): SSAActivation | undefined {
  return ssaActivations.find((a) => a.schoolId === schoolId && a.active);
}

/** Clear activation (e.g. once the SSA is uploaded). */
export function clearSsaActivation(schoolId: string): void {
  for (const a of ssaActivations) if (a.schoolId === schoolId && a.active) a.active = false;
}
