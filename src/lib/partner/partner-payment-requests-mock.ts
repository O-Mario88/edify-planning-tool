// Partner payment requests — the queue items that flow from CCEO
// confirmation → PL approval → Accountant clearance. Same row shape
// drives both the PL queue and the Accountant queue; the dashboards
// just filter by status.

import type { PartnerWorkflowStatus } from "./partner-workflow";

export type PartnerPaymentRequest = {
  id: string;
  partner: string;
  partnerOrgInitials: string;
  activitiesCount: number;
  schools: string[];
  confirmedBy: string;
  confirmedAtIso: string;
  approvedBy?: string;
  approvedAtIso?: string;
  totalUgx: number;
  evidenceComplete: boolean;
  cceoConfirmed: boolean;
  status: PartnerWorkflowStatus;
  scopeOk: boolean;
  notes?: string;
};

export const partnerPaymentRequests: PartnerPaymentRequest[] = [
  // For PL queue (AwaitingPlApproval)
  {
    id: "PR-001",
    partner: "Bright Future Education Partners",
    partnerOrgInitials: "BF",
    activitiesCount: 4,
    schools: ["Hope Primary", "Kireka Primary", "Namilyango Primary", "Grace Primary"],
    confirmedBy: "Paul Chinyama (CCEO)",
    confirmedAtIso: "2026-05-12T09:30:00Z",
    totalUgx: 1_400_000,
    evidenceComplete: true,
    cceoConfirmed: true,
    status: "AwaitingPlApproval",
    scopeOk: true,
  },
  {
    id: "PR-002",
    partner: "Literacy Training Uganda",
    partnerOrgInitials: "LT",
    activitiesCount: 3,
    schools: ["Sunrise Junior", "Maple Grove", "Eastview Junior"],
    confirmedBy: "Aisha Dar (CCEO)",
    confirmedAtIso: "2026-05-11T14:00:00Z",
    totalUgx: 925_000,
    evidenceComplete: true,
    cceoConfirmed: true,
    status: "AwaitingPlApproval",
    scopeOk: true,
  },
  {
    id: "PR-003",
    partner: "Numeracy First",
    partnerOrgInitials: "NF",
    activitiesCount: 2,
    schools: ["Hilltop Basic", "Riverside Primary"],
    confirmedBy: "Paul Chinyama (CCEO)",
    confirmedAtIso: "2026-05-10T11:15:00Z",
    totalUgx: 460_000,
    evidenceComplete: true,
    cceoConfirmed: true,
    status: "AwaitingPlApproval",
    scopeOk: false,
    notes: "One activity may fall outside the contracted scope — review carefully.",
  },
  // For Accountant queue (SentToAccountant)
  {
    id: "PR-004",
    partner: "Bright Future Education Partners",
    partnerOrgInitials: "BF",
    activitiesCount: 2,
    schools: ["St. Mary's Primary", "Bright Future PS"],
    confirmedBy: "Paul Chinyama (CCEO)",
    confirmedAtIso: "2026-05-08T09:00:00Z",
    approvedBy: "Daniel Mwangi (PL)",
    approvedAtIso: "2026-05-09T16:20:00Z",
    totalUgx: 700_000,
    evidenceComplete: true,
    cceoConfirmed: true,
    status: "SentToAccountant",
    scopeOk: true,
  },
  {
    id: "PR-005",
    partner: "Literacy Training Uganda",
    partnerOrgInitials: "LT",
    activitiesCount: 1,
    schools: ["Mukono Central PS"],
    confirmedBy: "Aisha Dar (CCEO)",
    confirmedAtIso: "2026-05-07T10:30:00Z",
    approvedBy: "Daniel Mwangi (PL)",
    approvedAtIso: "2026-05-08T13:00:00Z",
    totalUgx: 320_000,
    evidenceComplete: true,
    cceoConfirmed: true,
    status: "SentToAccountant",
    scopeOk: true,
  },
];

export function plQueue(): PartnerPaymentRequest[] {
  return partnerPaymentRequests.filter((r) => r.status === "AwaitingPlApproval");
}

export function accountantQueue(): PartnerPaymentRequest[] {
  return partnerPaymentRequests.filter((r) => r.status === "SentToAccountant");
}

export function fmtUgx(n: number): string {
  if (n >= 1_000_000) return `UGX ${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `UGX ${(n / 1_000).toFixed(0)}K`;
  return `UGX ${n}`;
}
