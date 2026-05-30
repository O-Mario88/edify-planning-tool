// Deprecated: canonical URL is /approvals.
//
// /approvals is the role-aware entry point that already routes CDs,
// RVPs, and PLs into their respective views (each with its own
// KPI row, queue, plan detail, and summary). The earlier standalone
// "Monthly Approval Governance" hub here largely duplicated that
// data for the CD view, so the bare URL now redirects.
//
// Workflow sub-pages still live under /budget/approvals/* (active,
// amendments, funds-matching, rvp-queue, [id]) — they are the
// canonical deep links for those flows. Only the bare URL redirects.

import { permanentRedirect } from "next/navigation";

export default function DeprecatedBudgetApprovalsHub() {
  permanentRedirect("/approvals");
}
