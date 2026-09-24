import logging
from dataclasses import dataclass

from django.db import transaction
from django.db.models import Sum
from django.utils import timezone
from apps.activities.models import (
    Activity,
    ActivityClosure,
    ClosureChecklist,
    ClosureBlocker,
    CompletedActivitySnapshot,
    ActivityReopenRequest,
    AnalyticsPublishRecord,
    ActivityTimelineEvent,
)
from apps.core.exceptions import BadRequest
from apps.evidence.models import EvidenceRecord
from apps.fund_requests.models import NetSuiteExpenseRecord, PartnerPayment
from apps.notifications.services import WorkflowNotificationService

logger = logging.getLogger(__name__)


#: Statuses in which the work has not happened (check 1). A visit request
#: waiting on the school owner is not yet a plan, and work that was declined,
#: cancelled or put off never happened; each read as executed, and with no
#: cost lines its finance also read as cleared (2026-09-13 ecosystem audit).
NOT_EXECUTED_STATUSES = (
    "not_planned",
    "awaiting_owner_approval",
    "planned",
    "scheduled",
    "assigned_to_partner",
    "partner_scheduled",
    "rejected",
    "cancelled",
    "deferred",
)

#: Statuses that carry IA verification (check 4).
IA_VERIFIED_STATUSES = ("ia_verified", "closed", "accountant_confirmed")

#: Advance states in which the accountant has cleared the money (check 6,
#: System B): "disbursed" and "accountability_pending" are pre-clearance — an
#: advance at accountability_pending means the responsible user submitted but
#: the accountant has NOT yet approved, so it must not count as cleared.
CLEARED_ADVANCE_STATUSES = ("accounted", "reimbursed")

#: Advance states in which money has left the account (check 7).
MONEY_MOVED_ADVANCE_STATUSES = (
    "disbursed",
    "accountability_pending",
    "accounted",
    "reimbursement_submitted",
    "reimbursement_disbursed",
    "reimbursed",
)

#: Blockers, in the order the checklist names them: (fact that clears it,
#: whether it applies only when finance is required, reason, responsible role).
_BLOCKER_RULES = (
    ("activity_executed", False, "Activity not executed", "CCEO"),
    ("evidence_uploaded", False, "Evidence Missing", "CCEO"),
    ("salesforce_id_entered", False, "Activity SF ID Missing", "CCEO"),
    ("ia_verified", False, "IA not verified", "ImpactAssessment"),
    ("accounts_cleared", True, "Accounts not cleared", "Accountant"),
    ("netsuite_id_entered", True, "NetSuite ID missing", "Accountant"),
    ("analytics_published", False, "Analytics not published", "ImpactAssessment"),
)

#: The related-row facts, read as annotations on the activity query so a list
#: of any length costs the one query that lists it.
_FACT_PREFIX = "closure_fact_"
_FACT_KEYS = tuple(
    _FACT_PREFIX + name
    for name in (
        "evidence",
        "cost_lines",
        "netsuite_expense",
        "cleared_advance",
        "moved_advance",
        "unaccounted_advance",
        "publish_status",
        "timeline",
    )
)


def _fact_annotations() -> dict:
    from django.db.models import Exists, OuterRef, Q, Subquery

    from apps.activities.models import ActivityScheduleCostLine
    from apps.fund_requests.models import AdvanceRequest

    activity = OuterRef("pk")
    moved = AdvanceRequest.objects.filter(
        activity=activity, status__in=MONEY_MOVED_ADVANCE_STATUSES
    )
    return {
        f"{_FACT_PREFIX}evidence": Exists(
            EvidenceRecord.objects.filter(activity=activity, quarantined=False)
        ),
        f"{_FACT_PREFIX}cost_lines": Exists(
            ActivityScheduleCostLine.objects.filter(activity=activity)
        ),
        f"{_FACT_PREFIX}netsuite_expense": Exists(
            NetSuiteExpenseRecord.objects.filter(activity=activity)
        ),
        f"{_FACT_PREFIX}cleared_advance": Exists(
            AdvanceRequest.objects.filter(
                activity=activity, status__in=CLEARED_ADVANCE_STATUSES
            )
        ),
        f"{_FACT_PREFIX}moved_advance": Exists(moved),
        f"{_FACT_PREFIX}unaccounted_advance": Exists(
            moved.filter(
                Q(accountability_netsuite_id__isnull=True)
                | Q(accountability_netsuite_id="")
            )
        ),
        f"{_FACT_PREFIX}publish_status": Subquery(
            AnalyticsPublishRecord.objects.filter(activity=activity).values("status")[
                :1
            ]
        ),
        f"{_FACT_PREFIX}timeline": Exists(
            ActivityTimelineEvent.objects.filter(activity=activity)
        ),
    }


def _reconcile_blockers(existing, wanted):
    """Which blocker rows to keep, delete and create for one activity.

    `existing` is the activity's rows oldest first; `wanted` its (reason,
    role) pairs. A row that still applies is kept, so its age stays the age
    of the block; duplicates and rows that no longer apply are deleted.
    """
    kept: dict[tuple[str, str], ClosureBlocker] = {}
    stale = []
    for blocker in existing:
        key = (blocker.blocking_reason, blocker.responsible_role)
        if key in wanted and key not in kept:
            kept[key] = blocker
        else:
            stale.append(blocker.pk)
    missing = [key for key in wanted if key not in kept]
    return kept, stale, missing


def _persist_batch(activities) -> tuple[int, int, int]:
    """Write the changed checklists and blockers of annotated activities."""
    facts = {a.pk: ClosureEligibilityService.facts(a) for a in activities}
    ids = list(facts)
    now = timezone.now()
    with transaction.atomic():
        current = {
            c.activity_id: c
            for c in ClosureChecklist.objects.filter(activity_id__in=ids)
        }
        created, updated = [], []
        for activity_id, derived in facts.items():
            fields = derived.checklist_fields()
            row = current.get(activity_id)
            if row is None:
                created.append(
                    ClosureChecklist(
                        activity_id=activity_id, last_evaluated_at=now, **fields
                    )
                )
            elif any(getattr(row, k) != v for k, v in fields.items()):
                for k, v in fields.items():
                    setattr(row, k, v)
                row.last_evaluated_at = now
                row.updated_at = now
                updated.append(row)
        # A closure act may create the same checklist concurrently; its row
        # wins and the next run compares against it.
        ClosureChecklist.objects.bulk_create(created, ignore_conflicts=True)
        if updated:
            ClosureChecklist.objects.bulk_update(
                updated,
                [*ClosureFacts.__dataclass_fields__, "last_evaluated_at", "updated_at"],
            )

        existing: dict[str, list[ClosureBlocker]] = {}
        for blocker in ClosureBlocker.objects.filter(activity_id__in=ids).order_by(
            "created_at", "id"
        ):
            existing.setdefault(blocker.activity_id, []).append(blocker)
        stale_ids, new_rows = [], []
        for activity_id, derived in facts.items():
            _kept, stale, missing = _reconcile_blockers(
                existing.get(activity_id, []), derived.blocker_specs()
            )
            stale_ids.extend(stale)
            new_rows.extend(
                ClosureBlocker(
                    activity_id=activity_id,
                    blocking_reason=reason,
                    responsible_role=role,
                )
                for reason, role in missing
            )
        if stale_ids:
            ClosureBlocker.objects.filter(pk__in=stale_ids).delete()
        ClosureBlocker.objects.bulk_create(new_rows)
    return len(created) + len(updated), len(new_rows), len(stale_ids)


@dataclass(frozen=True)
class ClosureFacts:
    """The nine closure checks for one activity, derived and never stored.

    One derivation serves every reader: the detail page and the close,
    publish and finance acts persist it as the activity's ClosureChecklist;
    the readiness queue reads it straight from its listing query.
    """

    activity_executed: bool
    evidence_uploaded: bool
    salesforce_id_entered: bool
    ia_verified: bool
    finance_required: bool
    accounts_cleared: bool
    netsuite_id_entered: bool
    analytics_published: bool
    audit_trail_saved: bool

    def blocker_specs(self) -> list[tuple[str, str]]:
        """(reason, responsible role) for every unmet check, in rule order."""
        return [
            (reason, role)
            for fact, finance_only, reason, role in _BLOCKER_RULES
            if not getattr(self, fact) and (self.finance_required or not finance_only)
        ]

    def checklist_fields(self) -> dict:
        return {name: getattr(self, name) for name in self.__dataclass_fields__}


class ClosureEligibilityService:
    """Evaluates if an activity meets all the requirements to be closed."""

    @staticmethod
    def with_facts(queryset):
        """Annotate an Activity queryset with every related-row closure fact.

        The readiness queue re-derived a stale checklist per row on GET, each
        inside its own transaction: ~1,000 statements and ~300 writes for one
        IA view at 16,000 schools, duplicated by every concurrent viewer
        (2026-09-23 performance rescue, R10). Annotated, the queue costs the
        one query that lists it, reads fresh facts, and writes nothing.
        """
        return queryset.annotate(**_fact_annotations())

    @staticmethod
    def facts(activity: Activity) -> ClosureFacts:
        """The activity's closure facts.

        Row facts come from the instance as the caller holds it; related-row
        facts from the annotations `with_facts` put on it, or from one query
        when it was loaded without them.
        """
        related = {
            key: getattr(activity, key) for key in _FACT_KEYS if hasattr(activity, key)
        }
        if len(related) != len(_FACT_KEYS):
            related = (
                type(activity)
                ._base_manager.filter(pk=activity.pk)
                .annotate(**_fact_annotations())
                .values(*_FACT_KEYS)
                .first()
            ) or dict.fromkeys(_FACT_KEYS)

        def fact(name):
            return bool(related[f"{_FACT_PREFIX}{name}"])

        from apps.activities.services import sf_kind_for_activity

        # Check 1: executed. Check 4: IA verified.
        executed = activity.status not in NOT_EXECUTED_STATUSES
        ia_verified = activity.status in IA_VERIFIED_STATUSES

        # Check 3: Salesforce ID entered — where the work has a Salesforce
        # record. SSA data gathering has none by design (IA confirmation does
        # not ask for one), so a verified, paid partner SSA Support could never
        # close (2026-09-12 journey walk).
        salesforce_id_entered = bool(activity.salesforce_activity_id) or (
            sf_kind_for_activity(activity) is None
        )

        # Check 5: finance required.
        finance_required = fact("cost_lines") or activity.delivery_type == "partner"

        # Check 6: Accounts Cleared — requires genuine ACCOUNTANT action, not
        # merely that money left the account. The mandate: "NO CLOSING AN
        # ACTIVITY WITHOUT ... FINANCE CLEARANCE." The two finance systems
        # each have a distinct accountant-clearance signal:
        #   System A (activity-level disburse+clear): the accountant's
        #     NetSuiteExpenseRecord entry IS the clearance step.
        #   System B (weekly advance accountability): the accountant approves
        #     submitted accountability, moving the advance to "accounted" (or
        #     "reimbursed").
        # Partners are paid directly by the accountant: payment_status "paid"
        # is the clearance.
        accounts_cleared = True
        if finance_required:
            if activity.delivery_type == "partner":
                accounts_cleared = activity.payment_status == "paid"
            else:
                accounts_cleared = fact("netsuite_expense") or fact("cleared_advance")

        # Check 7: NetSuite Code — accountability proof, required whenever
        # money moved. Two independent, equally-valid completion signals: the
        # accountant's own NetSuiteExpenseRecord entry (System A —
        # apps.fund_requests.finance_services.NetSuiteExpenseService) OR, for
        # advances that went through the responsible-user accountability chain
        # (System B — apps.fund_requests.advance_service.submit_accountability),
        # EVERY such advance carrying its own accountability NetSuite Code.
        # These are an OR, not an either/or keyed off AdvanceRequest status: an
        # activity disbursed via the System A queue still has its
        # AdvanceRequest rows move to "disbursed", but that must never by
        # itself demand the System B step System A's own flow never produces.
        #
        # NetSuite IDs exist for STAFF accountability. Partners are paid
        # directly by the accountant (owner, 2026-08-20): the payment (check 6)
        # IS the finance proof, and no NetSuite entry is asked of anyone for
        # partner-delivered work.
        netsuite_id_entered = True
        if finance_required and activity.delivery_type != "partner":
            netsuite_id_entered = fact("netsuite_expense") or (
                fact("moved_advance") and not fact("unaccounted_advance")
            )

        return ClosureFacts(
            activity_executed=executed,
            evidence_uploaded=fact("evidence"),
            salesforce_id_entered=salesforce_id_entered,
            ia_verified=ia_verified,
            finance_required=finance_required,
            accounts_cleared=accounts_cleared,
            netsuite_id_entered=netsuite_id_entered,
            # Check 8: analytics published. Check 9: audit trail saved.
            analytics_published=(
                related[f"{_FACT_PREFIX}publish_status"] == "published"
            ),
            audit_trail_saved=fact("timeline"),
        )

    @staticmethod
    def evaluate(activity: Activity) -> tuple[ClosureChecklist, list[ClosureBlocker]]:
        """Derive the facts and persist them as the activity's checklist.

        Blockers are reconciled, not rebuilt: one that still applies keeps its
        row, so its age on the Blocked Closures page is how long the activity
        has actually been blocked, not how long since somebody last looked.
        """
        with transaction.atomic():
            facts = ClosureEligibilityService.facts(activity)
            checklist, _ = ClosureChecklist.objects.update_or_create(
                activity=activity,
                defaults={
                    **facts.checklist_fields(),
                    "last_evaluated_at": timezone.now(),
                },
            )

            existing = ClosureBlocker.objects.filter(activity=activity).order_by(
                "created_at", "id"
            )
            kept, stale, missing = _reconcile_blockers(existing, facts.blocker_specs())
            if stale:
                ClosureBlocker.objects.filter(pk__in=stale).delete()
            for reason, role in missing:
                kept[(reason, role)] = ClosureBlocker.objects.create(
                    activity=activity, blocking_reason=reason, responsible_role=role
                )
            blockers = [kept[key] for key in facts.blocker_specs()]
            return checklist, blockers

    #: Activities the readiness queue lists but has not closed.
    OPEN_EXCLUDED_STATUSES = (
        "not_planned",
        "planned",
        "scheduled",
        "assigned_to_partner",
        "partner_scheduled",
        "closed",
    )

    @staticmethod
    def refresh_open(batch_size: int = 500) -> dict:
        """Persist the checklist and blockers of every open activity.

        The scheduled counterpart of the read-only queue: the Blocked
        Closures page and the System Health integrity checks read the
        persisted rows, which used to be refreshed only as a side effect of
        somebody opening the queue. Batched by primary key, each batch in its
        own short transaction, and only rows whose facts changed are written.
        """
        base = Activity.objects.filter(deleted_at__isnull=True).exclude(
            status__in=ClosureEligibilityService.OPEN_EXCLUDED_STATUSES
        )
        evaluated = checklists_written = blockers_added = blockers_removed = 0
        last_pk = ""
        while True:
            batch = list(
                ClosureEligibilityService.with_facts(
                    base.filter(pk__gt=last_pk).order_by("pk")
                )[:batch_size]
            )
            if not batch:
                break
            last_pk = batch[-1].pk
            written, added, removed = _persist_batch(batch)
            evaluated += len(batch)
            checklists_written += written
            blockers_added += added
            blockers_removed += removed
        return {
            "evaluated": evaluated,
            "checklistsWritten": checklists_written,
            "blockersAdded": blockers_added,
            "blockersRemoved": blockers_removed,
        }

    @staticmethod
    def _core_requirements_met(checklist: ClosureChecklist | ClosureFacts) -> bool:
        """Execution, evidence, SF ID, IA verification, and (if money moved)
        accounts cleared + NetSuite Code entered. Shared by is_eligible(), the
        readiness queue and AnalyticsPublishingService.publish_if_ready() so
        analytics is only ever marked published once these are genuinely
        true."""
        return (
            checklist.activity_executed
            and checklist.evidence_uploaded
            and checklist.salesforce_id_entered
            and checklist.ia_verified
            and (
                not checklist.finance_required
                or (checklist.accounts_cleared and checklist.netsuite_id_entered)
            )
        )

    @staticmethod
    def is_eligible(activity: Activity) -> bool:
        checklist, blockers = ClosureEligibilityService.evaluate(activity)
        # All required checks must be True to close
        return ClosureEligibilityService._core_requirements_met(checklist)


def _assert_may_close(actor, activity: Activity | None = None) -> None:
    """Authority at the act, not only at the door (CLOSE-01).

    Closure is terminal: it locks the record, freezes the financial snapshot,
    writes a hash-chained audit entry and moves the activity into Completed
    Activities. `ActivityClosureService.close` took `closed_by` on trust and
    stamped it onto the closure record, with the only guard living in one view
    (`frontend.views.closure_views.close_activity_action`, behind
    `@require_page_permission("planning")`).

    That is the FIN-03 and SEC-03 shape, and their fixes say why it matters:
    asserting at the act is what stops the next screen re-opening the hole. It
    was not a live hole — all three callers were gated: the endpoint by the
    page permission, and the two in `fund_requests.finance_services`
    (`clear_partner_payment`, `enter_netsuite_id`) as the automatic consequence
    of a payment act their own authority check had already cleared. Those two
    now pass `system=True` and say so at the call site. The point of asserting
    here is that a FOURTH caller would have opened a hole with nothing to catch
    it — the opposite of the partner-payment path, which asserts at three
    independent layers.

    The rule is deliberately the SAME rule the door already applies, read from
    the permission matrix rather than a role tuple, so there is no second
    standard to drift: whoever may reach the planning surface may close. That
    is CCEO, Programme Lead, Project Coordinator, Country Director and Admin —
    measured, not assumed. Impact Assessment and the Accountant are not among
    them, which is right: they verify and clear the money, and closure comes
    after both.

    CLOSE-01 was originally filed as "the closure test asserts an actor who
    cannot close". That half was wrong — a CCEO can close, and the check above
    is how that was established. What survived is this: nobody was checking.
    """
    from apps.core.exceptions import Forbidden
    from apps.core.permissions import RolePermissionService

    if isinstance(actor, str):
        from apps.accounts.models import User

        actor = User.objects.filter(id=actor).first()
    if actor is None or not RolePermissionService.can_view_page(actor, "planning"):
        raise Forbidden("Your role cannot close an activity.")
    # Since 2026-09-03 the Accountant and Impact Assessment reach Planning to
    # request owner-approved school visits (apps.planning.visit_requests).
    # That is a request door, not closure authority: they still verify and
    # clear the money, and closure comes after both.
    # Their OWN approved visit is the exception: it lands on their plan and
    # runs the ordinary lifecycle, and closing it is the last step of that.
    from apps.core.rbac import EdifyRole
    from apps.core.scoping import owner_ids

    if getattr(actor, "active_role", None) in (
        EdifyRole.PROGRAM_ACCOUNTANT.value,
        EdifyRole.IMPACT_ASSESSMENT.value,
    ):
        owns = activity is not None and str(activity.responsible_staff_id or "") in {
            str(i) for i in owner_ids(actor) if i
        }
        if not owns:
            raise Forbidden("Your role cannot close an activity.")


class ActivityClosureService:
    """Orchestrates locking and closing eligible activities."""

    @staticmethod
    def close(
        activity: Activity,
        closed_by: str = "system",
        bypass_checks: bool = False,
        *,
        system: bool = False,
    ) -> ActivityClosure:
        # Authority first, before eligibility and before any write. `system=True`
        # is the explicit opt-out for an automated closure with no human actor;
        # it is keyword-only and no caller passes it today, so a scheduled job
        # added later has to say so rather than inheriting a bypass from the
        # `closed_by="system"` default.
        if not system:
            _assert_may_close(closed_by, activity)
        # Check eligibility first
        if not bypass_checks and not ClosureEligibilityService.is_eligible(activity):
            raise BadRequest(
                "Activity does not meet final closure checklist requirements."
            )

        with transaction.atomic():
            # Take the row lock BEFORE re-reading status. The eligibility check
            # above runs outside this block against an unlocked in-memory
            # instance, so two concurrent callers (a double-click, or a retry
            # racing the original) can both pass it and both arrive here.
            #
            # The Activity write, ActivityClosure and CompletedActivitySnapshot
            # are all idempotent, which is what made this easy to miss -- but
            # the timeline event, the hash-chained AuditLog entry and the owner
            # notification below are append-only. Without this guard a double
            # close records the closure twice in the tamper-evident audit chain,
            # which is precisely the record used to reconstruct who closed what.
            locked = Activity.objects.select_for_update().filter(pk=activity.pk).first()
            if locked is not None and locked.status == "closed":
                existing = ActivityClosure.objects.filter(activity=activity).first()
                if existing is not None:
                    # Refresh the caller's instance so it reflects the winner's
                    # write rather than its own stale pre-close state.
                    activity.refresh_from_db()
                    return existing

            # Update Activity Status
            activity.status = "closed"
            activity.save(update_fields=["status", "updated_at"])

            # Create Closure detail record
            closure, _ = ActivityClosure.objects.update_or_create(
                activity=activity,
                defaults={
                    "closed_at": timezone.now(),
                    "closed_by": closed_by,
                    "status": "closed",
                },
            )

            # Freeze snapshot of financial stats. Sourced from AdvanceRequest
            # (System B) rather than the legacy Disbursement model (System A):
            # AdvanceDisbursementService.disburse_advance always mirrors its
            # writes into the same AdvanceRequest rows, so AdvanceRequest is
            # the superset covering both paths — reading only Disbursement
            # left activities funded purely through the weekly-advance path
            # (which never creates a Disbursement row) with a silent 0 here.
            budget_total = (
                activity.schedule_cost_lines.aggregate(s=Sum("amount"))["s"] or 0
            )
            adv_agg = activity.advance_requests.aggregate(
                d=Sum("disbursed_amount"),
                r=Sum("reimbursed_amount"),
                a=Sum("accounted_amount"),
            )
            partner_total = (
                PartnerPayment.objects.filter(activity=activity).aggregate(
                    s=Sum("amount_paid")
                )["s"]
                or 0
            )
            disb_total = (adv_agg["d"] or 0) + (adv_agg["r"] or 0) + partner_total
            actual_spend_total = (adv_agg["a"] or 0) + partner_total
            ns_rec = NetSuiteExpenseRecord.objects.filter(activity=activity).first()
            ns_id = (
                ns_rec.netsuite_expense_id
                if ns_rec
                else (
                    activity.advance_requests.exclude(
                        accountability_netsuite_id__isnull=True
                    )
                    .exclude(accountability_netsuite_id="")
                    .values_list("accountability_netsuite_id", flat=True)
                    .first()
                )
            )

            CompletedActivitySnapshot.objects.update_or_create(
                activity=activity,
                defaults={
                    "final_budget_amount": budget_total,
                    "disbursed_amount": disb_total,
                    "actual_spend_amount": actual_spend_total,
                    "netsuite_expense_id": ns_id,
                    "evidence_count": EvidenceRecord.objects.filter(
                        activity=activity
                    ).count(),
                    "snapshot_taken_at": timezone.now(),
                },
            )

            # Log event to Audit trail
            AuditTrailService.log_event(
                activity=activity,
                event_name="Closed",
                actor_id=closed_by,
                actor_role="System",
                description="Activity met all closure checklist conditions and is locked.",
            )

            # Closure is a security-critical event: the per-activity timeline
            # above is NOT tamper-evident — the hash-chained AuditLog must
            # also record it (ecosystem audit: closure was absent from the
            # chain entirely).
            try:
                from apps.audit.services import log as audit_log

                audit_log(
                    action="activity.closed",
                    subject_kind="Activity",
                    subject_id=activity.id,
                    actor_id=closed_by,
                    actor_role="System",
                    success=True,
                    payload={
                        "school_id": activity.school_id,
                        "final_budget": budget_total,
                        "disbursed": disb_total,
                        "actual_spend": actual_spend_total,
                    },
                )
            except Exception:  # noqa: BLE001 — the closure stands; the gap must not
                # A closure missing from the tamper-evident chain is exactly
                # what an audit looks for, and this used to vanish silently.
                logger.exception(
                    "Closure of activity %s was not written to the audit chain",
                    activity.id,
                )

            # Send Notification
            if activity.responsible_staff_id:
                WorkflowNotificationService.trigger(
                    event_type="activity_closed",
                    category="my_plan",
                    priority="normal",
                    title="Activity Closed",
                    body=f"Activity #{activity.id[:8]} is now closed and archived under Completed Activities.",
                    context_type="Activity",
                    context_id=activity.id,
                    recipients=[activity.responsible_staff_id],
                )

            return closure


class ActivityReopenService:
    """Manages reopening locked/closed activities with audited trails."""

    # Only work that actually reached the end of the pipeline can be reopened.
    # Everything here has already passed IA, so restoring "ia_verified" below
    # restores a state the activity genuinely held.
    REOPENABLE_STATUSES = ("closed", "accountant_confirmed", "ia_verified")

    @staticmethod
    def reopen(
        activity: Activity, reason: str, category: str, user_id: str
    ) -> ActivityReopenRequest:
        # Without this the non-invalidating branch below sets status to
        # "ia_verified" whatever the activity was before -- so reopening a
        # merely *scheduled* activity promoted it to a verified, target-credited
        # state with no evidence, no Salesforce ID and no IA decision. That
        # forges closure precondition #4 and grants immediate target credit.
        # Reopen means "undo a completed pipeline", so it needs something
        # completed to undo.
        with transaction.atomic():
            # Re-read the status under a row lock rather than trusting the
            # caller's in-memory instance. Checking it outside the transaction
            # let two concurrent callers both observe "closed" and both pass,
            # producing two reopen requests against a single close -- so an
            # activity accumulated more reopens than it had ever had closures,
            # and the second one reversed target credit that was never granted
            # twice. ActivityReopenRequest.activity is a plain ForeignKey, so
            # nothing at the database level catches the duplicate.
            locked = Activity.objects.select_for_update().filter(pk=activity.pk).first()
            current_status = locked.status if locked is not None else activity.status
            if current_status not in ActivityReopenService.REOPENABLE_STATUSES:
                raise BadRequest(
                    f"Only closed or verified activities can be reopened; this one "
                    f"is '{current_status}'. Nothing has been closed to reopen."
                )

            # The status gate alone cannot stop a double reopen, because a
            # successful reopen leaves the activity in "ia_verified" -- which is
            # itself reopenable. So the loser of the race re-reads a status that
            # still passes and files a second request against the same close.
            #
            # The real invariant is one reopen PER CLOSURE: reopening means
            # undoing a completed pipeline, and there is only ever one pipeline
            # to undo per close. Comparing against the last closure's timestamp
            # keeps a legitimate close -> reopen -> close -> reopen cycle
            # working, since each re-close stamps a fresh closed_at.
            last_closure = (
                ActivityClosure.objects.filter(activity=activity)
                .order_by("-closed_at")
                .first()
            )
            if last_closure is not None and last_closure.closed_at is not None:
                if ActivityReopenRequest.objects.filter(
                    activity=activity, created_at__gte=last_closure.closed_at
                ).exists():
                    raise BadRequest(
                        "This activity has already been reopened since it was "
                        "last closed."
                    )
            # Create reopen record
            req = ActivityReopenRequest.objects.create(
                activity=activity,
                reopened_by=user_id,
                reason=reason,
                category=category,
                approved=True,
            )

            # Reset activity status. Categories that INVALIDATE the achievement
            # (wrong evidence, wrong Salesforce ID, wrong school, duplicate)
            # must not land on "ia_verified" — that status still counts as
            # achieved in every target engine, so the bad work would stay
            # credited. "returned_by_ia" is the platform's own correction
            # state: target ledger reverses, and the owner gets the fix To-Do.
            invalidating = {
                "wrong_evidence",
                "wrong_salesforce_id",
                "wrong_school",
                "duplicate_discovered",
            }
            if category in invalidating:
                activity.status = "returned_by_ia"
                activity.ia_verification_status = "returned"
                activity.save(
                    update_fields=["status", "ia_verification_status", "updated_at"]
                )
                # The comment above promises "target ledger reverses" — the
                # personal ledger does on its next rebuild, but the milestone
                # credit engine needed this explicit reversal or invalidated
                # work stayed credited against the Uganda cascade.
                from apps.hr.milestone_progress import reverse_activity_progress

                invalidated = activity
                transaction.on_commit(lambda: reverse_activity_progress(invalidated))
            else:
                # Finance/audit/analytics corrections: the field work itself
                # stands, so keep the verified (credited) state.
                activity.status = "ia_verified"
                activity.save(update_fields=["status", "updated_at"])

            # Update closure record status
            ActivityClosure.objects.filter(activity=activity).update(
                status="reopened", notes=f"Reopened by {user_id}. Reason: {reason}"
            )

            # Reset analytics publishing state to trigger recalculations
            AnalyticsPublishRecord.objects.filter(activity=activity).update(
                status="recalculation_required"
            )

            # Log event to Audit trail
            AuditTrailService.log_event(
                activity=activity,
                event_name="Reopened",
                actor_id=user_id,
                actor_role="Admin",
                description=f"Reopened activity under category: {category}. Reason: {reason}",
            )

            return req


class AnalyticsPublishingService:
    """Simulates publishing verified and cleared activity metrics into the central analytics database."""

    @staticmethod
    def publish(activity: Activity) -> AnalyticsPublishRecord:
        with transaction.atomic():
            rec, _ = AnalyticsPublishRecord.objects.update_or_create(
                activity=activity,
                defaults={"status": "published", "published_at": timezone.now()},
            )
            return rec

    @staticmethod
    def publish_if_ready(activity: Activity) -> ClosureChecklist:
        """Marks analytics published only once genuinely earned — never a
        blind force-satisfy. Evaluates the checklist and, only when the
        activity has actually met the core closure requirements (executed,
        evidence, SF ID, IA verified, and finance cleared if money moved),
        publishes analytics and re-evaluates so callers see the fresh state.
        A failed/ineligible close attempt must never leave a false
        "published" record behind."""
        checklist, _ = ClosureEligibilityService.evaluate(activity)
        if ClosureEligibilityService._core_requirements_met(checklist):
            AnalyticsPublishingService.publish(activity)
            checklist, _ = ClosureEligibilityService.evaluate(activity)
        return checklist


class AuditTrailService:
    """Maintains a vertical timeline audit record for each activity."""

    @staticmethod
    def log_event(
        activity: Activity,
        event_name: str,
        actor_id: str,
        actor_role: str,
        description: str = "",
    ) -> ActivityTimelineEvent:
        return ActivityTimelineEvent.objects.create(
            activity=activity,
            event_name=event_name,
            actor_id=actor_id,
            actor_role=actor_role,
            description=description,
        )
