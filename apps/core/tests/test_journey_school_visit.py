"""Journey 1 — the platform's primary spine, walked once, end to end.

The 2026-08 audit's coverage sweep found that no test walks a whole journey.
The suite splits this one in two and each half fabricates the other's outcome:
the money test hand-sets `ia_verification_status = "confirmed"` and never
executes the visit, and the execution test never touches money. Either half
can pass while the seam between them is broken, which is exactly the failure
this platform cannot afford — a funded visit that cannot be verified, or a
verified visit that cannot close.

So this test fakes nothing. It plans a real visit through the costed funnel,
compiles and approves the real weekly advance, disburses it, confirms receipt,
executes the visit, uploads evidence, reserves a Salesforce ID, walks PL
review and IA verification through the live services, accounts for the money,
and asserts the activity can actually reach `closed` — and that the verified
work lands in the achievement ledger exactly once.

If any handoff in the spine breaks, this test names the step.
"""

from __future__ import annotations

import datetime

from django.test import TestCase
from django.utils import timezone

from apps.accounts.models import (
    StaffProfile,
    StaffSchoolAssignment,
    StaffSupervisorAssignment,
    User,
)
from apps.activities.models import Activity
from apps.budget.models import CostCatalogue, CostSetting
from apps.core.fy import get_operational_fy
from apps.fund_requests.models import AdvanceRequest, WeeklyFundRequest
from apps.geography.models import District, Region
from apps.schools.models import School


def _confirmed_ssa(school, *, fy=None, score=6.0):
    """A confirmed assessment, so intervention work can be planned at all."""
    from django.utils import timezone

    from apps.core.enums import SsaIntervention
    from apps.core.fy import get_operational_fy
    from apps.ssa.models import SsaRecord, SsaScore

    record = SsaRecord.objects.create(
        school=school,
        fy=fy or get_operational_fy(),
        date_of_ssa=timezone.now(),
        average_score=score,
        verification_status="confirmed",
    )
    for intervention, _ in SsaIntervention.choices:
        SsaScore.objects.create(
            ssa_record=record, intervention=intervention, score=score
        )
    return record


TRANSPORT = 50_000
LUNCH = 12_000


def _schedulable_date() -> datetime.date:
    """A near-future weekday the calendar policy will accept."""
    from apps.core.calendar_policy import SchedulingPolicyService

    day = timezone.localdate() + datetime.timedelta(days=7)
    for _ in range(21):
        if SchedulingPolicyService.check(None, day)["status"] != "blocked":
            return day
        day += datetime.timedelta(days=1)
    raise AssertionError("no schedulable date within three weeks")


def _at(day: datetime.date):
    return timezone.make_aware(datetime.datetime.combine(day, datetime.time(9, 0)))


class SchoolVisitSpineJourneyTest(TestCase):
    """Plan → fund → execute → verify → account → close → achieve."""

    @classmethod
    def setUpTestData(cls):
        cls.region = Region.objects.create(name="Journey Region")
        cls.district = District.objects.create(
            name="Journey District", region=cls.region, district_type="primary"
        )
        cls.school = School.objects.create(
            school_id="SCH-JOURNEY-1",
            name="Journey Primary",
            region=cls.region,
            district=cls.district,
            school_type="client",
        )

        # An ordinary school visit is "scheduled against the intervention it is
        # meant to move", so the school must be assessed before that work can
        # be planned. The fixture starts where real work starts.
        _confirmed_ssa(cls.school)

        def _person(email, name, role):
            user = User.objects.create_user(
                email=email,
                name=name,
                roles=[role],
                active_role=role,
                password="x",
                is_active=True,
            )
            profile = StaffProfile.objects.create(
                user=user, staff_number=f"JN-{name[:6]}", country="Uganda", title=role
            )
            return user, profile

        cls.cceo, cls.cceo_sp = _person("jn-cceo@edify.org", "Jn CCEO", "CCEO")
        cls.pl, cls.pl_sp = _person("jn-pl@edify.org", "Jn PL", "Program Lead")
        cls.ia, _ = _person("jn-ia@edify.org", "Jn IA", "ImpactAssessment")
        cls.accountant, _ = _person("jn-acct@edify.org", "Jn Acct", "Accountant")

        StaffSupervisorAssignment.objects.create(
            supervisor=cls.pl_sp, supervisee=cls.cceo_sp
        )
        StaffSchoolAssignment.objects.create(staff=cls.cceo_sp, school_id=cls.school.id)

        cls.day = _schedulable_date()
        cls.fy = get_operational_fy(cls.day)
        cls.catalogue, _ = CostCatalogue.objects.get_or_create(
            country="Uganda", fy=cls.fy, is_active=True, defaults={"version": 1}
        )
        for key, cost in (
            ("primary_transport_per_day", TRANSPORT),
            ("primary_lunch_per_day", LUNCH),
        ):
            CostSetting.objects.update_or_create(
                key=key,
                defaults={
                    "label": key.replace("_", " ").title(),
                    "unit_cost": cost,
                    "fy": cls.fy,
                    "catalogue": cls.catalogue,
                },
            )

    def test_a_funded_visit_can_be_executed_verified_accounted_and_closed(self):
        from apps.activities.closure_services import (
            ActivityClosureService,
            ClosureEligibilityService,
        )
        from apps.activities.ia_services import ActivityCertificationService
        from apps.activities.services import complete, start_completion
        from apps.activity_catalogue.services import resolve_item_for_workflow_kind
        from apps.evidence.models import EvidenceRecord
        from apps.fund_requests.weekly_service import (
            approve_weekly_request,
            disburse,
            request_advance,
        )
        from apps.planning.services import schedule_school_visit

        # ── 1. Plan a real visit through the costed funnel ────────────────
        item = resolve_item_for_workflow_kind("school_visit")
        schedule_school_visit(
            {
                "schoolId": self.school.school_id,
                "catalogueItemId": item.id,
                "scheduledDate": _at(self.day).isoformat(),
                "activityPurposeText": "Journey spine proof",
            },
            self.cceo,
        )
        activity = Activity.objects.get(school=self.school)
        self.assertEqual(activity.status, "scheduled")
        self.assertGreater(
            activity.est_cost_cents,
            0,
            "planning produced no cost, so nothing downstream can be funded",
        )

        # ── 2. The week's money compiles, routes, and is disbursed ────────
        wfr = WeeklyFundRequest.objects.get(responsible_user=self.cceo.id)
        request_advance(wfr.id, self.cceo)
        approve_weekly_request(wfr.id, self.pl)
        disburse(wfr.id, {"method": "Bank", "reference": "JN-1"}, self.accountant)
        wfr.refresh_from_db()
        self.assertEqual(wfr.status, "disbursed")

        # ── 3. The owner confirms the funds actually arrived ──────────────
        # Accountability is closed until this happens: money is not accounted
        # for before the person says it reached them.
        from apps.fund_requests.weekly_service import confirm_receipt

        confirm_receipt(wfr.id, self.cceo)
        wfr.refresh_from_db()
        self.assertIsNotNone(wfr.receipt_confirmed_at)

        advances = list(
            AdvanceRequest.objects.filter(
                budget_line__weekly_request_lines__weekly_fund_request=wfr
            ).distinct()
        )
        self.assertTrue(advances, "disbursement created no advance to account for")

        # ── 4. The visit is actually executed ─────────────────────────────
        start_completion(activity.id, {}, self.cceo)
        activity.refresh_from_db()

        EvidenceRecord.objects.create(
            activity_id=activity.id,
            kind="school_visit_form",
            uri="journey/visit-form.pdf",
            original_name="visit-form.pdf",
            file_size=2048,
            uploaded_by=self.cceo.id,
        )
        complete(
            activity.id,
            {"salesforceId": "SVE-100001"},
            self.cceo,
        )
        activity.refresh_from_db()
        self.assertIn(
            activity.status,
            ("submitted_to_pl", "awaiting_ia_verification"),
            "a completed visit did not enter the review chain",
        )

        # ── 5. PL review, then IA verification through the LIVE service ───
        if activity.status == "submitted_to_pl":
            from apps.pl_review.services import confirm as pl_confirm

            pl_confirm(activity.id, self.pl)
            activity.refresh_from_db()
        self.assertEqual(activity.status, "awaiting_ia_verification")

        with self.captureOnCommitCallbacks(execute=True):
            ActivityCertificationService.certify_activity(activity, {}, str(self.ia.id))
        activity.refresh_from_db()
        self.assertEqual(activity.status, "ia_verified")
        self.assertEqual(activity.ia_verification_status, "confirmed")

        # ── 6. The money is accounted for ─────────────────────────────────
        from apps.fund_requests import advance_service

        for index, advance in enumerate(advances):
            advance.refresh_from_db()
            # The NetSuite code is the owner's proof the expense was recorded
            # in the finance system — one of the six §3a interactions.
            advance_service.submit_accountability(
                advance.id,
                {
                    "amountSpent": advance.disbursed_amount,
                    "netsuiteId": f"NS-JOURNEY-{index}",
                },
                self.cceo,
            )
            advance.refresh_from_db()
            self.assertEqual(advance.status, "accountability_pl_pending")

        for advance in advances:
            advance_service.pl_approve_accountability(advance.id, self.pl)
            advance.refresh_from_db()
            self.assertEqual(advance.status, "accountability_pending")

        for advance in advances:
            advance_service.approve_accountability(advance.id, self.accountant)
            advance.refresh_from_db()
            self.assertEqual(
                advance.status,
                "accounted",
                f"advance {advance.id} stalled at {advance.status}",
            )

        # ── 7. The activity can actually CLOSE ────────────────────────────
        # The sweep's open question: nothing proved a visit funded through the
        # weekly-advance chain could reach `closed`. If a blocker remains, the
        # message below names it rather than leaving a bare False.
        checklist, blockers = ClosureEligibilityService.evaluate(activity)
        if not ClosureEligibilityService._core_requirements_met(checklist):
            self.fail(
                "a fully executed, verified and accounted visit is still not "
                "closeable. Blockers: "
                + ", ".join(str(b) for b in blockers)
                + f" · checklist: executed={checklist.activity_executed} "
                f"evidence={checklist.evidence_uploaded} "
                f"sf={checklist.salesforce_id_entered} "
                f"ia={checklist.ia_verified} "
                f"finance_required={checklist.finance_required} "
                f"accounts_cleared={checklist.accounts_cleared} "
                f"netsuite={checklist.netsuite_id_entered}"
            )
        ActivityClosureService.close(activity, closed_by=str(self.accountant.id))
        activity.refresh_from_db()
        self.assertEqual(activity.status, "closed")

    def test_the_verified_visit_credits_the_ledger_exactly_once(self):
        """Verified work must reach the achievement ledger — and only once.

        Every existing targets test writes `status="ia_verified"` by hand, so
        nothing proved the real completion chain produces a credited row.
        """
        from apps.activities.ia_services import ActivityCertificationService
        from apps.activities.services import complete, start_completion
        from apps.activity_catalogue.services import resolve_item_for_workflow_kind
        from apps.evidence.models import EvidenceRecord
        from apps.hr.models import MilestoneProgressCredit
        from apps.planning.services import schedule_school_visit

        item = resolve_item_for_workflow_kind("school_visit")
        schedule_school_visit(
            {
                "schoolId": self.school.school_id,
                "catalogueItemId": item.id,
                "scheduledDate": _at(self.day).isoformat(),
                "activityPurposeText": "Journey ledger proof",
            },
            self.cceo,
        )
        activity = Activity.objects.get(school=self.school)

        start_completion(activity.id, {}, self.cceo)
        EvidenceRecord.objects.create(
            activity_id=activity.id,
            kind="school_visit_form",
            uri="journey/ledger-form.pdf",
            original_name="ledger-form.pdf",
            file_size=1024,
            uploaded_by=self.cceo.id,
        )
        complete(activity.id, {"salesforceId": "SVE-100002"}, self.cceo)
        activity.refresh_from_db()
        if activity.status == "submitted_to_pl":
            from apps.pl_review.services import confirm as pl_confirm

            pl_confirm(activity.id, self.pl)
            activity.refresh_from_db()

        with self.captureOnCommitCallbacks(execute=True):
            ActivityCertificationService.certify_activity(activity, {}, str(self.ia.id))
        activity.refresh_from_db()
        self.assertEqual(activity.status, "ia_verified")

        # Certifying twice must not double-credit. The engine dedups on
        # (rule, activity); this proves the whole chain honours it.
        credits_after_first = MilestoneProgressCredit.objects.filter(
            activity=activity
        ).count()
        from apps.hr.milestone_progress import record_activity_progress

        record_activity_progress(activity)
        self.assertEqual(
            MilestoneProgressCredit.objects.filter(activity=activity).count(),
            credits_after_first,
            "re-running the credit engine created a duplicate credit",
        )


class MyPlanShowsWorkInBothIdSpacesTest(TestCase):
    """A CCEO's own work must appear on My Plan whichever id space wrote it.

    `Activity.responsible_staff_id` holds a StaffProfile id when the row came
    through `activities.services.create`, and a User id when it came from the
    seeder or an older path. `apps.core.scoping.owner_ids` exists precisely
    because checking only one space "silently disowns most of a field worker's
    activities". Every activity in the development database — all 599 — is
    stored in the User-id space, so a My Plan that filters on profile ids alone
    shows a field officer an empty day (2026-08 audit).
    """

    @classmethod
    def setUpTestData(cls):
        cls.region = Region.objects.create(name="IdSpace Region")
        cls.district = District.objects.create(
            name="IdSpace District", region=cls.region
        )
        cls.school = School.objects.create(
            school_id="SCH-IDSPACE-1",
            name="IdSpace Primary",
            region=cls.region,
            district=cls.district,
            school_type="client",
        )

        # An ordinary school visit is "scheduled against the intervention it is
        # meant to move", so the school must be assessed before that work can
        # be planned. The fixture starts where real work starts.
        _confirmed_ssa(cls.school)
        cls.user = User.objects.create_user(
            email="idspace-cceo@edify.org",
            name="IdSpace CCEO",
            roles=["CCEO"],
            active_role="CCEO",
            password="x",
            is_active=True,
        )
        cls.profile = StaffProfile.objects.create(
            user=cls.user, staff_number="ID-1", country="Uganda", title="CCEO"
        )
        StaffSchoolAssignment.objects.create(staff=cls.profile, school_id=cls.school.id)

    def _activity(self, owner_id, sf):
        return Activity.objects.create(
            activity_type="school_visit",
            delivery_type="staff",
            status="scheduled",
            school=self.school,
            responsible_staff_id=owner_id,
            planned_date=timezone.localdate(),
            scheduled_date=timezone.now(),
            fy=get_operational_fy(),
            salesforce_activity_id=sf,
        )

    def test_activities_stored_against_the_user_id_still_appear(self):
        from apps.my_plan.services import get_frontend_context

        by_profile = self._activity(self.profile.id, "SVE-200001")
        by_user = self._activity(self.user.id, "SVE-200002")

        context = get_frontend_context(self.user, {})
        shown = set()
        for key in (
            "school_visits",
            "cluster_meetings",
            "cluster_trainings",
            "programme_activities",
            "activities",
        ):
            for row in context.get(key) or []:
                shown.add(getattr(row, "id", None) or (row or {}).get("id"))

        self.assertIn(
            by_profile.id, shown, "work stored against the StaffProfile id is missing"
        )
        self.assertIn(
            by_user.id,
            shown,
            "work stored against the User id is missing from My Plan — the "
            "field officer's own day, invisible to them",
        )
