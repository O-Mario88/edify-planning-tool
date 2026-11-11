/**
 * What the Acting Leadership screen and the Work as list show (the web's
 * /acting-leadership and its role switcher, apps.acting). Owner, 2026-10-07:
 * an acting leader does not have every privilege of the seat; "their major
 * task is manage and follow up with the team members". An appointment never
 * changes who somebody is, so every row names the permanent role beside the
 * acting one.
 */
import type { ActingAppointment, ActingCapacity } from '../../gen/edify/identity/v1/acting_pb';
import type { Session } from '../../gen/edify/identity/v1/identity_pb';

/** The web's own address for the page. */
export const ACTING_URL = '/acting-leadership';

export type AppointmentAction = 'change' | 'cancel';

export const APPOINTMENT_ACTION_LABELS: Readonly<Record<AppointmentAction, string>> = {
  change: 'Change month',
  cancel: 'Cancel appointment',
};

/** A row's Actions menu: what the gateway says this person may do to it. */
export function appointmentActions(a: Pick<ActingAppointment, 'canChangeMonth' | 'canCancel'>): AppointmentAction[] {
  const actions: AppointmentAction[] = [];
  if (a.canChangeMonth) {
    actions.push('change');
  }
  if (a.canCancel) {
    actions.push('cancel');
  }
  return actions;
}

/** A state in colour: green active, blue upcoming, plain ended, red cancelled. */
export function stateTone(state: string): string {
  switch (state) {
    case 'active':
      return 'good';
    case 'upcoming':
      return 'info';
    case 'cancelled':
      return 'alert';
  }
  return 'plain';
}

/** What cancelling does, in the web's words. */
export function cancelConsequence(
  a: Pick<ActingAppointment, 'state' | 'appointeeName' | 'shortLabel' | 'appointeeRole' | 'monthLabel'>,
): string {
  if (a.state === 'active') {
    return `${a.appointeeName} loses ${a.shortLabel} access at once and returns to working as ${a.appointeeRole}.`;
  }
  return `${a.appointeeName} will not become ${a.shortLabel} in ${a.monthLabel}. The appointment stays in History.`;
}

/** Whether a request now is made in the acting capacity. */
export function isWorkingAsActing(session: Pick<Session, 'activeRole' | 'acting'>): boolean {
  const acting = session.acting;
  return Boolean(acting?.inCapacity && session.activeRole === acting.appointeeRole);
}

export interface WorkAsChoice {
  /** A role, or "acting" for today's appointment. */
  readonly key: string;
  readonly label: string;
  readonly isCurrent: boolean;
}

/**
 * Work as: the roles the account holds, and today's acting appointment
 * beside them ("Acting Program Lead · November 2026"). Exactly one is
 * current: the acting capacity while it is in use, otherwise the role.
 */
export function workAsChoices(session: Pick<Session, 'roles' | 'activeRole' | 'acting'>): WorkAsChoice[] {
  const actingNow = isWorkingAsActing(session);
  const choices: WorkAsChoice[] = session.roles.map((role) => ({
    key: role,
    label: role,
    isCurrent: !actingNow && role === session.activeRole,
  }));
  const acting: ActingCapacity | undefined = session.acting;
  if (acting) {
    choices.push({ key: 'acting', label: `${acting.label} · ${acting.monthLabel}`, isCurrent: actingNow });
  }
  return choices;
}

/** Whether Work as is offered at all. */
export function offersWorkAs(session: Pick<Session, 'roles' | 'acting'>): boolean {
  return session.roles.length > 1 || Boolean(session.acting);
}
