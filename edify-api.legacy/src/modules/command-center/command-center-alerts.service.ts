import { Injectable } from '@nestjs/common';
import { ActivityStatus, NotificationPriority, Prisma } from '@prisma/client';
import { PrismaService } from '../../prisma/prisma.service';
import { AuthUser } from '../../common/auth/auth-user';
import { getOperationalFY } from '../../common/fy/fy.util';
import {
  AlertConditionResult,
  conditionHash,
  Dismissal,
  OpenAlert,
  sortAlerts,
  summarize,
  visibleAlerts,
} from './alert-visibility';

// ── Command-center alerts (spec §13, §17) ────────────────────────────────────
//
// Persistent operational risks generated from live data conditions. Unlike a
// notification (a one-shot workflow event), a command-center alert REAPPEARS
// every time the generator runs while the underlying issue is unresolved, and is
// auto-resolved the moment the condition clears. Users may dismiss it for a
// window; it comes back when the window lapses (and the issue still exists).
//
// The generator runs on read (GET /command-center/alerts) so the rail is always
// live without a cron — and the same identity (conditionHash) means re-running
// never creates duplicates.

const SCHEDULED_STATES: ActivityStatus[] = [
  ActivityStatus.planned, ActivityStatus.scheduled, ActivityStatus.assigned_to_partner,
  ActivityStatus.partner_scheduled, ActivityStatus.in_progress, ActivityStatus.evidence_uploaded,
  ActivityStatus.evidence_accepted, ActivityStatus.salesforce_id_required, ActivityStatus.awaiting_ia_verification,
  ActivityStatus.ia_verified, ActivityStatus.accountant_confirmed, ActivityStatus.completed,
];
const VISIT_TYPES = ['school_visit', 'follow_up_visit', 'coaching_visit', 'in_school_support', 'core_visit'];
const TRAINING_TYPES = ['training', 'school_improvement_training', 'cluster_training', 'core_training'];
const CORE_PACKAGE_TARGET = 4;

/** How long a dismissal hides an alert (spec §13: "dismissed temporarily"). */
const DEFAULT_DISMISS_HOURS = 24;
const MAX_DISMISS_HOURS = 24 * 14; // a fortnight ceiling — risk can't be buried

@Injectable()
export class CommandCenterAlertsService {
  constructor(private readonly prisma: PrismaService) {}

  // ── The live data conditions (spec §13 examples) ──────────────────────────
  // Each returns a count; count 0 means the condition is resolved and any open
  // alert for it is closed. Country scope: these are operational risks, not a
  // single user's queue (that's the recommendation feed in command-center.today).
  private async evaluateConditions(): Promise<AlertConditionResult[]> {
    const fy = getOperationalFY();
    const now = new Date();
    const out: AlertConditionResult[] = [];

    const [
      schoolsNoSsa,
      readyNoPlan,
      partnerEvidenceOverdue,
      activitiesOverdue,
      evidenceReturned,
      evidenceToReview,
      ssaAwaitingVerification,
      fundRequestsAwaiting,
      paymentsReady,
      potentialCore,
      championSchools,
    ] = await Promise.all([
      this.prisma.school.count({ where: { deletedAt: null, clusterStatus: 'clustered', currentFySsaStatus: { not: 'done' } } }),
      this.prisma.school.count({ where: { deletedAt: null, planningReadiness: 'ready', activities: { none: { deletedAt: null, status: { in: SCHEDULED_STATES } } } } }),
      this.prisma.activity.count({ where: { deletedAt: null, deliveryType: 'partner', evidenceStatus: 'none', scheduledDate: { lt: now }, status: { in: [ActivityStatus.in_progress, ActivityStatus.partner_scheduled, ActivityStatus.assigned_to_partner] } } }),
      this.prisma.activity.count({ where: { deletedAt: null, status: { in: [ActivityStatus.planned, ActivityStatus.scheduled] }, scheduledDate: { lt: now } } }),
      this.prisma.activity.count({ where: { deletedAt: null, evidenceStatus: 'returned' } }),
      this.prisma.activity.count({ where: { deletedAt: null, status: ActivityStatus.evidence_uploaded } }),
      this.prisma.ssaRecord.count({ where: { deletedAt: null, fy, verificationStatus: 'pending' } }),
      this.prisma.fundRequest.count({ where: { status: 'submitted' } }),
      this.prisma.activity.count({ where: { deletedAt: null, iaVerificationStatus: 'confirmed', paymentStatus: { notIn: ['accountant_cleared', 'paid', 'closed', 'rejected'] } } }),
      this.prisma.school.count({ where: { deletedAt: null, schoolType: 'potential_core' } }),
      this.prisma.school.count({ where: { deletedAt: null, schoolType: 'champion' } }),
    ]);

    // Core-package gaps (a Core school needs 4 visits + 4 trainings).
    const coreSchools = await this.prisma.school.findMany({
      where: { deletedAt: null, schoolType: 'core' },
      select: { id: true, activities: { where: { deletedAt: null, status: { in: SCHEDULED_STATES } }, select: { activityType: true } } },
      take: 1000,
    });
    const coreGapCount = coreSchools.filter((s) => {
      const visits = s.activities.filter((a) => VISIT_TYPES.includes(a.activityType)).length;
      const trainings = s.activities.filter((a) => TRAINING_TYPES.includes(a.activityType)).length;
      return visits < CORE_PACKAGE_TARGET || trainings < CORE_PACKAGE_TARGET;
    }).length;

    const add = (alertType: string, severity: NotificationPriority, count: number, title: string, body: string, targetRoute: string, contextType?: string) => {
      out.push({ alertType, severity, scope: 'country', count, title, body, targetRoute, contextType });
    };

    add('schools_without_ssa', 'urgent', schoolsNoSsa, `${schoolsNoSsa} school${schoolsNoSsa === 1 ? '' : 's'} without SSA`, 'Clustered schools have no current-FY SSA. Schedule SSA so planning can proceed.', '/planning', 'data_quality_issue');
    add('schools_ready_no_plan', 'urgent', readyNoPlan, `${readyNoPlan} school${readyNoPlan === 1 ? ' has' : 's have'} SSA but no plan`, 'Schools are planning-ready with no scheduled visit or training.', '/planning', 'school');
    add('core_package_gaps', 'high', coreGapCount, `${coreGapCount} core school${coreGapCount === 1 ? '' : 's'} missing package items`, 'Core schools are missing visits/trainings from their 4+4 package.', '/planning', 'school');
    add('partner_activities_past_due', 'urgent', partnerEvidenceOverdue, `${partnerEvidenceOverdue} partner activit${partnerEvidenceOverdue === 1 ? 'y is' : 'ies are'} past due`, 'Partner work is overdue with no evidence uploaded.', '/partners', 'partner_assignment');
    add('activities_past_due', 'urgent', activitiesOverdue, `${activitiesOverdue} activit${activitiesOverdue === 1 ? 'y is' : 'ies are'} past due`, 'Scheduled activities are past their date and not completed.', '/my-plan', 'my_plan_activity');
    add('evidence_returned', 'high', evidenceReturned, `${evidenceReturned} evidence submission${evidenceReturned === 1 ? '' : 's'} returned`, 'Returned evidence is awaiting correction and re-submission.', '/evidence', 'evidence');
    add('evidence_to_review', 'high', evidenceToReview, `${evidenceToReview} evidence submission${evidenceToReview === 1 ? '' : 's'} to review`, 'Uploaded evidence is waiting for staff review.', '/evidence', 'evidence');
    add('ssa_awaiting_verification', 'high', ssaAwaitingVerification, `${ssaAwaitingVerification} SSA record${ssaAwaitingVerification === 1 ? '' : 's'} awaiting verification`, 'Partner-collected SSA needs IA verification.', '/verification', 'verification');
    add('fund_requests_awaiting_approval', 'high', fundRequestsAwaiting, `${fundRequestsAwaiting} fund request${fundRequestsAwaiting === 1 ? '' : 's'} awaiting approval`, 'Fund requests are waiting in an approval queue.', '/approvals', 'fund_request');
    add('payments_ready', 'high', paymentsReady, `${paymentsReady} verified item${paymentsReady === 1 ? '' : 's'} ready for payment`, 'IA-confirmed work is ready for payment/accountability.', '/disbursements', 'payment');
    add('potential_core_unverified', 'normal', potentialCore, `${potentialCore} potential core school${potentialCore === 1 ? '' : 's'} need verification`, 'Potential core schools require leadership verification.', '/analytics', 'school');
    add('champion_schools_review', 'low', championSchools, `${championSchools} champion school${championSchools === 1 ? '' : 's'} need recognition/review`, 'Champion schools qualify for recognition or donor review.', '/analytics', 'school');

    return out;
  }

  /** Recompute conditions and reconcile the CommandCenterAlert table: upsert an
   *  open row for every active condition, resolve the rows whose condition has
   *  cleared. Idempotent — safe to run on every read. Best-effort: a generation
   *  failure must never break the read path. */
  async generate(): Promise<void> {
    let conditions: AlertConditionResult[];
    try {
      conditions = await this.evaluateConditions();
    } catch {
      return;
    }
    const active = new Set<string>();
    for (const c of conditions.filter((x) => x.count > 0)) {
      const hash = conditionHash(c.alertType, c.scope);
      active.add(hash);
      const data = {
        alertType: c.alertType, severity: c.severity, scope: c.scope,
        title: c.title, body: c.body, targetRoute: c.targetRoute, contextType: c.contextType ?? null,
        status: 'open', resolvedAt: null,
      };
      try {
        await this.prisma.commandCenterAlert.upsert({
          where: { conditionHash: hash },
          create: { ...data, conditionHash: hash },
          update: data,
        });
      } catch {
        /* best-effort per-alert */
      }
    }
    // Resolve any open alert whose condition is no longer active. An alert
    // disappears for good ONLY when the issue clears (spec §13).
    try {
      const open = await this.prisma.commandCenterAlert.findMany({ where: { status: 'open' }, select: { id: true, conditionHash: true } });
      const toResolve = open.filter((a) => !active.has(a.conditionHash)).map((a) => a.id);
      if (toResolve.length) {
        await this.prisma.commandCenterAlert.updateMany({ where: { id: { in: toResolve } }, data: { status: 'resolved', resolvedAt: new Date() } });
      }
    } catch {
      /* best-effort */
    }
  }

  /** The alerts a user should currently see — generated live, minus the ones the
   *  user has dismissed within their (still-open) window. */
  async list(user: AuthUser) {
    await this.generate();
    const open = (await this.prisma.commandCenterAlert.findMany({ where: { status: 'open' } })) as OpenAlert[];
    const dismissals = (await this.prisma.commandCenterAlertDismissal.findMany({
      where: { userId: user.userId, alertId: { in: open.map((a) => a.id) } },
      select: { alertId: true, dismissedUntil: true },
    })) as Dismissal[];
    const visible = sortAlerts(visibleAlerts(open, dismissals));
    return visible.map((a) => ({
      id: a.id, alertType: a.alertType, severity: a.severity, scope: a.scope,
      title: a.title, body: a.body, targetRoute: a.targetRoute,
      contextType: a.contextType, contextId: a.contextId, createdAt: a.createdAt,
    }));
  }

  /** Severity-bucketed counts for the command-center header (spec §17). */
  async summary(user: AuthUser) {
    const visible = await this.list(user);
    return summarize(visible);
  }

  /** Dismiss an alert for this user for a window (default 24h). The alert
   *  reappears when the window lapses if the issue is still unresolved. */
  async dismiss(user: AuthUser, alertId: string, hours?: number) {
    const alert = await this.prisma.commandCenterAlert.findUnique({ where: { id: alertId }, select: { id: true } });
    if (!alert) return { ok: false };
    const h = Math.min(Math.max(1, hours ?? DEFAULT_DISMISS_HOURS), MAX_DISMISS_HOURS);
    const dismissedUntil = new Date(Date.now() + h * 3600 * 1000);
    await this.prisma.commandCenterAlertDismissal.upsert({
      where: { alertId_userId: { alertId, userId: user.userId } },
      create: { alertId, userId: user.userId, dismissedUntil },
      update: { dismissedUntil },
    });
    return { ok: true, dismissedUntil };
  }
}

// re-export so the controller/tests import one module
export { conditionHash } from './alert-visibility';
export type AlertWhere = Prisma.CommandCenterAlertWhereInput;
