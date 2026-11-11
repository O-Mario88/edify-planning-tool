/**
 * What the Cluster Leader's meeting screens share: every member school of the
 * cluster (for inviting), and how a meeting plan's status reads — always in
 * words, with a tone only as a second signal.
 */
import { useEffect, useState } from 'react';

import { describe, useSession } from '../../auth/SessionContext';
import type { MemberSchool } from '../../gen/edify/clusters/v1/leadership_pb';

/** A cluster's schools fit in a few pages; this is a guard, not a limit anyone meets. */
const MAX_PAGES = 20;

export interface Members {
  readonly schools: readonly MemberSchool[] | null;
  readonly error: string;
}

/** Every member school of the cluster, all pages. */
export function useAllMembers(clusterId: string): Members {
  const { api } = useSession();
  const [state, setState] = useState<Members>({ schools: null, error: '' });
  useEffect(() => {
    let isLive = true;
    const load = async () => {
      const all: MemberSchool[] = [];
      for (let page = 1; page <= MAX_PAGES; page++) {
        const answer = await api.listMemberSchools(clusterId, { page, search: '' });
        all.push(...answer.schools);
        if (page >= (answer.page?.totalPages ?? 1)) {
          break;
        }
      }
      return all;
    };
    load()
      .then((schools) => isLive && setState({ schools, error: '' }))
      .catch((cause: unknown) => isLive && setState({ schools: null, error: describe(cause) }));
    return () => {
      isLive = false;
    };
  }, [api, clusterId]);
  return state;
}

export interface PlanStatus {
  readonly label: string;
  readonly tone: string;
  /** What it means for the leader, in a sentence. */
  readonly meaning: string;
}

const PLAN_STATUSES: Readonly<Record<string, PlanStatus>> = {
  draft: { label: 'Draft', tone: 'plain', meaning: 'Not yet sent to staff.' },
  submitted: { label: 'Planned', tone: 'info', meaning: 'Sent to your CCEO for review.' },
  approved: { label: 'Approved', tone: 'good', meaning: 'Approved. Your CCEO schedules it in Edify next.' },
  returned: { label: 'Returned', tone: 'caution', meaning: 'Returned by staff for changes. Edit it and send it again.' },
  scheduled: { label: 'Scheduled', tone: 'good', meaning: 'Scheduled in Edify. Invitations carried over to it.' },
  cancelled: { label: 'Cancelled', tone: 'alert', meaning: 'Cancelled.' },
};

export function planStatus(status: string): PlanStatus {
  return PLAN_STATUSES[status] ?? { label: status, tone: 'plain', meaning: '' };
}

/** How a leader invites schools; there is no default, so it is always said. */
export const INVITE_CHANNELS = [
  { value: 'phone', label: 'Phone call' },
  { value: 'sms', label: 'SMS' },
  { value: 'whatsapp', label: 'WhatsApp' },
  { value: 'email', label: 'Email' },
  { value: 'in_person', label: 'In person' },
] as const;

export function channelLabel(channel: string): string {
  return INVITE_CHANNELS.find((choice) => choice.value === channel)?.label ?? channel;
}

/** "10:00 AM" and similar; empty is allowed (the field is optional on a training). */
export function isTimeText(value: string): boolean {
  return value.trim() === '' || /^([01]?\d|2[0-3])[:.][0-5]\d(\s?[AaPp][Mm])?$/.test(value.trim());
}

/** apps/core/enums.py SsaStatus, as the web words it. */
const SSA_STATUSES: Readonly<Record<string, string>> = {
  not_done: 'Not Done',
  scheduled: 'Scheduled',
  partner_assigned: 'Partner Assigned',
  done: 'Done',
};

export function ssaStatusLabel(status: string): string {
  return SSA_STATUSES[status] ?? status;
}

/**
 * A key for one form's submission, made once when the form opens: a retry
 * after a lost answer sends the same key, and the gateway answers with the
 * action it already saved instead of a second one. It names an attempt; it
 * is not a secret.
 */
export function newSubmissionKey(now: number = Date.now()): string {
  const random = () => Math.floor(Math.random() * 36 ** 8).toString(36).padStart(8, '0');
  return `ca-${now.toString(36)}-${random()}${random()}`;
}

/** The register's tabs for a leader (brief part 12). */
export const ACTION_TABS = [
  { key: 'open', label: 'Open' },
  { key: 'waiting', label: 'Waiting' },
  { key: 'completed', label: 'Completed' },
] as const;

export type ActionTab = (typeof ACTION_TABS)[number]['key'];

export const PRIORITIES = [
  { value: 'normal', label: 'Normal' },
  { value: 'high', label: 'High' },
  { value: 'urgent', label: 'Urgent' },
];

/** A staff member's queues of Cluster Support Requests (brief part 5.3). */
export const SUPPORT_QUEUES = [
  { key: 'new', label: 'New' },
  { key: 'clarification', label: 'Clarification' },
  { key: 'accepted', label: 'Accepted' },
  { key: 'planned', label: 'Planned' },
  { key: 'in_progress', label: 'In progress' },
  { key: 'overdue', label: 'Overdue' },
  { key: 'completed', label: 'Completed' },
];

export type SupportScope = 'mine' | 'team';
