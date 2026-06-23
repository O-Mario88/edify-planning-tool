import { EdifyRole, FundRequestStatus } from '@prisma/client';

// ── Fund request routing state machine (spec §11) ───────────────────────────
//
// A fund request flows up a role chain — PL → CD → RVP → Accountant — with an
// explicit status at every hop, a return path at every hop, and a notification
// event for every transition (the events the rule engine already knows how to
// route — notification-rules.ts). This module is the pure, DB-free source of
// truth for that chain so it can be exhaustively unit-tested (spec §20) and
// reused by the service, the approval dashboard and the timeline.
//
// "scope" decides whether the request needs RVP sign-off: only a COUNTRY-level
// request routes CD → RVP → Accountant; a team/own request routes CD →
// Accountant directly.

export type FundScope = 'own' | 'team' | 'country';

/** The forward chain of "waiting" statuses a request passes through. */
export const FUND_FORWARD_CHAIN: FundRequestStatus[] = [
  'draft',
  'submitted_to_pl',
  'submitted_to_cd',
  'submitted_to_rvp',
  'sent_to_accountant',
  'disbursed',
  'closed',
];

/** The approval the chain is waiting on at each status → the approver's role. */
export const APPROVER_FOR_STATUS: Partial<Record<FundRequestStatus, EdifyRole>> = {
  submitted_to_pl: 'CountryProgramLead',
  submitted_to_cd: 'CountryDirector',
  submitted_to_rvp: 'RegionalVicePresident',
  sent_to_accountant: 'ProgramAccountant',
};

/** Per-stage return status + the role who returned it (routes back to submitter). */
export const RETURN_STATUS_FOR_APPROVER: Partial<Record<EdifyRole, FundRequestStatus>> = {
  CountryProgramLead: 'returned_by_pl',
  CountryDirector: 'returned_by_cd',
  RegionalVicePresident: 'returned_by_rvp',
  ProgramAccountant: 'returned_by_accountant',
};

export type Transition = {
  /** The status the request moves to. */
  status: FundRequestStatus;
  /** The domain event to emit (drives notifications + audit + timeline). */
  event: string;
};

/** The event emitted when a request is first submitted into the chain. */
export function submitTransition(): Transition {
  return { status: 'submitted_to_pl', event: 'FundRequestSubmittedToPL' };
}

/**
 * Advance the request when the current approver APPROVES. Returns the next
 * status + the event to emit, or null when the request is not at an approvable
 * stage. Country-scope requests route CD → RVP → Accountant; others skip RVP.
 */
export function approveTransition(current: FundRequestStatus, scope: FundScope): Transition | null {
  switch (current) {
    case 'submitted_to_pl':
      // PL approved → goes to CD. (Notifies submitter + CD.)
      return { status: 'submitted_to_cd', event: 'FundRequestApprovedByPL' };
    case 'submitted_to_cd':
      // CD approved → RVP for country budgets, else straight to the accountant.
      return scope === 'country'
        ? { status: 'submitted_to_rvp', event: 'FundRequestApprovedByCD' }
        : { status: 'sent_to_accountant', event: 'FundRequestApprovedByCD' };
    case 'submitted_to_rvp':
      // RVP approved → accountant. (Notifies CD + Accountant.)
      return { status: 'sent_to_accountant', event: 'FundRequestApprovedByRVP' };
    case 'sent_to_accountant':
      // Accountant disbursed → funds out. (Notifies submitter + PL/CD.)
      return { status: 'disbursed', event: 'FundsDisbursed' };
    default:
      return null;
  }
}

/** Return the request to the submitter for correction from the current stage. */
export function returnTransition(current: FundRequestStatus): Transition | null {
  const approver = APPROVER_FOR_STATUS[current];
  if (!approver) return null;
  const status = RETURN_STATUS_FOR_APPROVER[approver];
  if (!status) return null;
  return { status, event: 'FundRequestReturned' };
}

/** Whether a role is the approver the request is currently waiting on. */
export function isCurrentApprover(current: FundRequestStatus, role: EdifyRole): boolean {
  return APPROVER_FOR_STATUS[current] === role;
}

/** True for any of the per-stage "returned_by_*" statuses. */
export function isReturned(status: FundRequestStatus): boolean {
  return status === 'returned_by_pl' || status === 'returned_by_cd' || status === 'returned_by_rvp' || status === 'returned_by_accountant';
}

/** True once the request has reached a terminal (no further routing) status. */
export function isTerminal(status: FundRequestStatus): boolean {
  return status === 'closed' || status === 'disbursed';
}
