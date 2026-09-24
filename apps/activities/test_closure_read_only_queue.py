"""The closure readiness queue reads facts and writes nothing (PERF-01 / R10).

A GET of /activities/closure/ re-derived every stale checklist in the request,
each in its own transaction — ~12 statements and several writes per row, 4.2 s
for one IA view at 16,000 schools and ~25 s under load, repeated by every
concurrent viewer. The facts now arrive as annotations on the listing query,
the persisted checklist is written where it is acted on, and a scheduled job
keeps the stored copy current for the Blocked Closures page and System Health.
"""

from datetime import date

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from apps.accounts.models import StaffProfile
from apps.activities.closure_services import ClosureEligibilityService, ClosureFacts
from apps.activities.models import (
    Activity,
    ActivityScheduleCostLine,
    ActivityTimelineEvent,
    AnalyticsPublishRecord,
    ClosureBlocker,
    ClosureChecklist,
)
from apps.evidence.models import EvidenceRecord
from apps.fund_requests.models import AdvanceRequest, NetSuiteExpenseRecord
from apps.geography.models import District, Region
from apps.schools.models import School


def legacy_facts(activity) -> dict:
    """The per-activity derivation the queue ran before, query by query.

    Kept here as the oracle: the annotated derivation must agree with it on
    every scenario below.
    """
    from apps.activities.services import sf_kind_for_activity

    executed = activity.status not in [
        "not_planned",
        "awaiting_owner_approval",
        "planned",
        "scheduled",
        "assigned_to_partner",
        "partner_scheduled",
        "rejected",
        "cancelled",
        "deferred",
    ]
    evidence = EvidenceRecord.objects.filter(
        activity=activity, quarantined=False
    ).exists()
    sf = bool(activity.salesforce_activity_id) or sf_kind_for_activity(activity) is None
    ia = activity.status in ["ia_verified", "closed", "accountant_confirmed"]
    finance = (
        activity.schedule_cost_lines.exists() or activity.delivery_type == "partner"
    )
    cleared = True
    if finance:
        if activity.delivery_type == "partner":
            cleared = activity.payment_status == "paid"
        else:
            cleared = (
                NetSuiteExpenseRecord.objects.filter(activity=activity).exists()
                or activity.advance_requests.filter(
                    status__in=["accounted", "reimbursed"]
                ).exists()
            )
    netsuite = True
    if finance and activity.delivery_type != "partner":
        from django.db.models import Q

        has_record = NetSuiteExpenseRecord.objects.filter(activity=activity).exists()
        moved = activity.advance_requests.filter(
            status__in=[
                "disbursed",
                "accountability_pending",
                "accounted",
                "reimbursement_submitted",
                "reimbursement_disbursed",
                "reimbursed",
            ]
        )
        every = not moved.filter(
            Q(accountability_netsuite_id__isnull=True)
            | Q(accountability_netsuite_id="")
        ).exists()
        netsuite = has_record or (moved.exists() and every)
    rec = AnalyticsPublishRecord.objects.filter(activity=activity).first()
    return {
        "activity_executed": executed,
        "evidence_uploaded": evidence,
        "salesforce_id_entered": sf,
        "ia_verified": ia,
        "finance_required": finance,
        "accounts_cleared": cleared,
        "netsuite_id_entered": netsuite,
        "analytics_published": rec is not None and rec.status == "published",
        "audit_trail_saved": ActivityTimelineEvent.objects.filter(
            activity=activity
        ).exists(),
    }


class ClosureQueueReadOnlyTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user(
            email="closure-queue@edify.test",
            password="password123",
            name="Closure Queue",
            roles=["Admin"],
            active_role="Admin",
            is_active=True,
        )
        StaffProfile.objects.create(id="closure-queue-staff", user=cls.user)
        region = Region.objects.create(name="Closure Queue Region")
        district = District.objects.create(name="Closure Queue District", region=region)
        cls.school = School.objects.create(
            school_id="CLOSURE-QUEUE-SCHOOL",
            name="Closure Queue School",
            region=region,
            district=district,
        )

    def setUp(self):
        self.client.force_login(self.user)
        self._n = 0

    def _activity(self, **fields):
        self._n += 1
        defaults = {
            "school": self.school,
            "activity_type": "school_visit",
            "delivery_type": "staff",
            "status": "completed",
            "responsible_staff_id": "closure-queue-staff",
            "planned_date": date(2026, 7, 2),
        }
        defaults.update(fields)
        return Activity.objects.create(**defaults)

    def _cost_line(self, activity, amount=50_000):
        return ActivityScheduleCostLine.objects.create(
            activity=activity,
            cost_setting_key=f"transport-{activity.pk}",
            label="Transport",
            unit_cost=amount,
            quantity=1,
            amount=amount,
        )

    def _advance(self, activity, status, netsuite=None):
        line = self._cost_line(activity)
        return AdvanceRequest.objects.create(
            activity=activity,
            budget_line=line,
            fy="2026",
            quarter="Q4",
            amount=line.amount,
            status=status,
            disbursed_amount=line.amount,
            accountability_netsuite_id=netsuite,
        )

    def _scenarios(self):
        """Every branch of the nine checks, one activity each."""
        plain = self._activity()
        evidenced = self._activity(status="ia_verified", salesforce_activity_id="SF-1")
        EvidenceRecord.objects.create(
            activity=evidenced, kind="visit_form", uri="a.pdf", uploaded_by="x"
        )
        quarantined = self._activity()
        EvidenceRecord.objects.create(
            activity=quarantined,
            kind="visit_form",
            uri="q.pdf",
            uploaded_by="x",
            quarantined=True,
        )
        not_executed = self._activity(status="cancelled")
        partner_unpaid = self._activity(delivery_type="partner", payment_status="none")
        partner_paid = self._activity(delivery_type="partner", payment_status="paid")
        staff_no_clearance = self._activity()
        self._cost_line(staff_no_clearance)
        staff_netsuite = self._activity()
        self._cost_line(staff_netsuite)
        NetSuiteExpenseRecord.objects.create(
            activity=staff_netsuite,
            netsuite_expense_id=f"NS-{staff_netsuite.pk}",
            expense_date=date(2026, 7, 2),
            amount_entered=50_000,
            entered_by="acct",
        )
        accounted_with_code = self._activity()
        self._advance(accounted_with_code, "accounted", netsuite="NS-ADV-1")
        accounted_without_code = self._activity()
        self._advance(accounted_without_code, "accounted")
        pending_accountability = self._activity()
        self._advance(pending_accountability, "accountability_pending", netsuite="")
        published = self._activity()
        AnalyticsPublishRecord.objects.create(
            activity=published, status="published", published_at=timezone.now()
        )
        failed_publish = self._activity()
        AnalyticsPublishRecord.objects.create(activity=failed_publish, status="failed")
        timeline = self._activity()
        ActivityTimelineEvent.objects.create(
            activity=timeline, event_name="Started", actor_id="x", actor_role="CCEO"
        )
        ssa_gathering = self._activity(salesforce_record_type_snapshot="NONE")
        return [
            plain,
            evidenced,
            quarantined,
            not_executed,
            partner_unpaid,
            partner_paid,
            staff_no_clearance,
            staff_netsuite,
            accounted_with_code,
            accounted_without_code,
            pending_accountability,
            published,
            failed_publish,
            timeline,
            ssa_gathering,
        ]

    def test_annotated_facts_match_the_legacy_derivation_on_every_branch(self):
        activities = self._scenarios()
        annotated = {
            a.pk: a
            for a in ClosureEligibilityService.with_facts(
                Activity.objects.filter(pk__in=[a.pk for a in activities])
            )
        }
        for activity in activities:
            with self.subTest(activity=activity.pk):
                expected = legacy_facts(activity)
                self.assertEqual(
                    ClosureEligibilityService.facts(
                        annotated[activity.pk]
                    ).checklist_fields(),
                    expected,
                )
                # And the unannotated path (the closure acts) agrees too.
                fresh = Activity.objects.get(pk=activity.pk)
                self.assertEqual(
                    ClosureEligibilityService.facts(fresh).checklist_fields(),
                    expected,
                )

    def test_the_queue_get_writes_nothing(self):
        self._scenarios()
        before = (ClosureChecklist.objects.count(), ClosureBlocker.objects.count())
        response = self.client.get("/activities/closure/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            (ClosureChecklist.objects.count(), ClosureBlocker.objects.count()), before
        )

    def test_the_queue_costs_the_same_at_any_length(self):
        for _ in range(3):
            self._activity()
        self.client.get("/activities/closure/")  # warm per-process caches
        from django.db import connection
        from django.test.utils import CaptureQueriesContext

        with CaptureQueriesContext(connection) as small:
            self.client.get("/activities/closure/")
        for _ in range(25):
            self._advance(self._activity(), "accounted", netsuite=None)
        with CaptureQueriesContext(connection) as large:
            response = self.client.get("/activities/closure/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(large), len(small))
        writes = [
            q["sql"]
            for q in large.captured_queries
            if q["sql"].lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE"))
            and ("closure_" in q["sql"])
        ]
        self.assertEqual(writes, [])

    def test_the_queue_buckets_by_the_derived_facts(self):
        ready = self._activity(status="ia_verified", salesforce_activity_id="SF-R")
        EvidenceRecord.objects.create(
            activity=ready, kind="visit_form", uri="r.pdf", uploaded_by="x"
        )
        finance = self._activity(status="ia_verified", salesforce_activity_id="SF-F")
        EvidenceRecord.objects.create(
            activity=finance, kind="visit_form", uri="f.pdf", uploaded_by="x"
        )
        self._cost_line(finance)
        response = self.client.get("/activities/closure/")
        self.assertIn(ready, response.context["ready"])
        self.assertIn(finance, response.context["finance_pending"])

    def test_a_blocker_that_still_applies_keeps_its_age(self):
        activity = self._activity()
        _checklist, blockers = ClosureEligibilityService.evaluate(activity)
        evidence_blocker = next(
            b for b in blockers if b.blocking_reason == "Evidence Missing"
        )
        ClosureBlocker.objects.filter(pk=evidence_blocker.pk).update(
            created_at=timezone.now() - timezone.timedelta(days=9)
        )
        # The SF ID arrives; the evidence blocker is still there, unaged.
        activity.salesforce_activity_id = "SF-AGE"
        activity.save()
        _checklist, blockers = ClosureEligibilityService.evaluate(activity)
        reasons = [b.blocking_reason for b in blockers]
        self.assertNotIn("Activity SF ID Missing", reasons)
        kept = next(b for b in blockers if b.blocking_reason == "Evidence Missing")
        self.assertEqual(kept.pk, evidence_blocker.pk)
        self.assertGreaterEqual((timezone.now() - kept.created_at).days, 9)
        self.assertEqual(
            ClosureBlocker.objects.filter(activity=activity).count(), len(blockers)
        )

    def test_refresh_persists_open_activities_and_a_rerun_writes_nothing(self):
        activities = self._scenarios()
        planned = self._activity(status="planned")
        first = ClosureEligibilityService.refresh_open(batch_size=4)
        open_ids = {a.pk for a in activities}
        self.assertEqual(first["evaluated"], len(open_ids))
        self.assertEqual(
            set(ClosureChecklist.objects.values_list("activity_id", flat=True)),
            open_ids,
        )
        self.assertFalse(ClosureChecklist.objects.filter(activity=planned).exists())
        for activity in activities:
            with self.subTest(activity=activity.pk):
                stored = ClosureChecklist.objects.get(activity=activity)
                expected = legacy_facts(activity)
                self.assertEqual(
                    {k: getattr(stored, k) for k in expected},
                    expected,
                )
                self.assertEqual(
                    sorted(
                        ClosureBlocker.objects.filter(activity=activity).values_list(
                            "blocking_reason", flat=True
                        )
                    ),
                    sorted(
                        reason
                        for reason, _role in ClosureFacts(**expected).blocker_specs()
                    ),
                )

        second = ClosureEligibilityService.refresh_open(batch_size=4)
        self.assertEqual(second["checklistsWritten"], 0)
        self.assertEqual(second["blockersAdded"], 0)
        self.assertEqual(second["blockersRemoved"], 0)

        # A fact that changes is picked up on the next run, and only there.
        target = activities[0]
        EvidenceRecord.objects.create(
            activity=target, kind="visit_form", uri="late.pdf", uploaded_by="x"
        )
        third = ClosureEligibilityService.refresh_open(batch_size=4)
        self.assertEqual(third["checklistsWritten"], 1)
        self.assertEqual(third["blockersRemoved"], 1)
        self.assertTrue(ClosureChecklist.objects.get(activity=target).evidence_uploaded)

    def test_the_refresh_is_a_registered_scheduled_job(self):
        from apps.realtime import jobs
        from apps.realtime.registry import JOB_NAMES

        self.assertIn("closure_checklist_refresh", JOB_NAMES)
        self.assertTrue(callable(jobs.closure_checklist_refresh_job))
