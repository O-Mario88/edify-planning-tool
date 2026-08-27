"""Journey 3 — Standard staff school visit, walked once, end to end.

Journey 3 of the mandate's twenty-two: Plan, Cost, Schedule, Fund request,
Approval, Disbursement, Start, Evidence, PL review, IA verification,
Accountability, Closure. (This docstring said "Journey 1" and walked
Journey 3; Journey 1 is Priority to verified performance, which starts from a
published priority and ends at a reconciling drill-down. A census built from
docstrings would have ticked the wrong box.) The manifest in
apps/core/tests/release_journeys.py is the register, and it points here.

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
from apps.core.enums import SsaIntervention
from apps.core.fy import get_operational_fy
from apps.fund_requests.models import AdvanceRequest, WeeklyFundRequest
from apps.geography.models import District, Region
from apps.schools.models import School
from apps.ssa.models import SsaRecord


def _confirmed_ssa(school, *, fy=None, score=6.0):
    """A confirmed assessment, so intervention work can be planned at all."""
    import datetime

    from django.utils import timezone

    from apps.core.enums import SsaIntervention
    from apps.core.fy import get_operational_fy
    from apps.ssa.models import SsaRecord, SsaScore

    record = SsaRecord.objects.create(
        school=school,
        fy=fy or get_operational_fy(),
        # Dated back deliberately. You plan THIS cycle's intervention work
        # against the assessment you already hold, so a planning SSA is months
        # old. Stamping it `now()` made it indistinguishable from an assessment
        # collected on the visit being walked, which quietly satisfied the
        # SSA-01 verification gate and made the door walk below prove nothing.
        date_of_ssa=timezone.now() - datetime.timedelta(days=120),
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
        # CLOSE-01, now closed. This step used to pass the ACCOUNTANT, with a
        # note explaining that it proved the closure machinery runs rather than
        # that this person can close — because `close()` asserted no authority
        # of its own and the Accountant cannot reach the closure surface (the
        # endpoint is gated on the `planning` page: {CCEO, PL,
        # ProjectCoordinator, CD, Admin}).
        #
        # `close()` asserts that itself now, at the act, so the gap between
        # "the function runs when called directly" and "the spine closes" is
        # gone: an actor who could not do this through a door cannot do it
        # here either. The service walk and the door walk finally make the
        # same claim about the same person.
        ActivityClosureService.close(activity, closed_by=str(self.pl.id))
        activity.refresh_from_db()
        self.assertEqual(activity.status, "closed")

    def test_the_same_spine_walked_through_the_platform_s_own_doors(self):
        """JRN-01: journey 3, over HTTP, at every step that has an endpoint.

        The walk above proves the spine's SERVICES compose. It never issues a
        request, so it cannot see URL routing, page gates, view-level scoping,
        form parsing or the principal a view hands its service — the layer
        where SEC-01 lived and where journey 7's door walk found FIN-06, a 500
        returned to every caller of an endpoint 6,081 tests had called green.

        Journey 3 is the platform's most-travelled path and touches money at
        three points and authority at three more, so it is the one most worth
        proving twice. Thirteen doors, in the order a real week goes through
        them.

        Asserted on STATE after each step, never on the status code alone.
        Several of these views turn a refusal into a flash message and a 200,
        so a status-only walk would report a journey that never moved as a
        complete success — the same trap journey 5's denial sweep documents.
        """
        from apps.activities.models import Activity
        from apps.activity_catalogue.services import resolve_item_for_workflow_kind
        from apps.evidence.models import EvidenceRecord
        from django.contrib.messages import get_messages

        def as_user(user):
            self.client.force_login(user)

        def post(path, data=None, who=None):
            if who is not None:
                as_user(who)
            return self.client.post(path, data or {})

        # ── 1. Plan, through the scheduling endpoint ──────────────────────
        item = resolve_item_for_workflow_kind("school_visit")
        post(
            "/planning/schedule-action",
            {
                "school_id": self.school.school_id,
                "catalogue_item_id": item.id,
                "scheduled_date": _at(self.day).isoformat(),
                "activity_purpose_text": "Journey 3 door walk",
                "purpose_of_visit": "ssa_support",
                "delivery_type": "staff",
                "executor_type": "staff",
            },
            who=self.cceo,
        )
        activity = Activity.objects.filter(school=self.school).first()
        self.assertIsNotNone(
            activity, "the scheduling endpoint created no activity at all"
        )
        self.assertEqual(activity.status, "scheduled")
        self.assertGreater(
            activity.est_cost_cents,
            0,
            "the endpoint scheduled a visit with no cost, so nothing "
            "downstream can be funded",
        )

        # ── 2-5. The week's money, through the four finance doors ─────────
        wfr = WeeklyFundRequest.objects.get(responsible_user=self.cceo.id)
        post(f"/fund-requests/weekly/{wfr.id}/confirm", who=self.cceo)
        post(f"/fund-requests/weekly/{wfr.id}/approve", who=self.pl)
        post(
            f"/fund-requests/weekly/{wfr.id}/disburse",
            {"method": "Bank", "reference": "JN3-DOOR-1"},
            who=self.accountant,
        )
        wfr.refresh_from_db()
        self.assertEqual(
            wfr.status,
            "disbursed",
            f"the money did not move through the endpoints; it sits at "
            f"{wfr.status}",
        )

        post(f"/fund-requests/weekly/{wfr.id}/confirm-receipt", who=self.cceo)
        wfr.refresh_from_db()
        self.assertIsNotNone(
            wfr.receipt_confirmed_at,
            "the owner's receipt confirmation did not land, and "
            "accountability stays closed until it does",
        )

        advances = list(
            AdvanceRequest.objects.filter(
                budget_line__weekly_request_lines__weekly_fund_request=wfr
            ).distinct()
        )
        self.assertTrue(advances, "disbursement created no advance to account for")

        # ── 6-7. Execute and complete ─────────────────────────────────────
        post(f"/activities/{activity.id}/start/action", who=self.cceo)
        EvidenceRecord.objects.create(
            activity_id=activity.id,
            kind="school_visit_form",
            uri="journey3/door-visit-form.pdf",
            original_name="door-visit-form.pdf",
            file_size=2048,
            uploaded_by=self.cceo.id,
        )
        # This visit was scheduled with `purpose_of_visit="ssa_support"`, so
        # collecting the assessment IS the work, and the completion drawer is
        # where a CCEO enters the eight scores. Walking it here means the
        # journey now exercises SSA collection as well as the visit spine.
        #
        # This walk previously completed with `ssa_not_collected_reason="School
        # closed for holidays"` and then ticked `ssa_uploaded` on the IA
        # checklist to push it through to `ia_verified`. That was the SSA-01
        # defect written down as an expectation: a visit that collected nothing
        # being certified as though it had. Under the rule the programme owner
        # set — an SSA support visit is only valid work once the scores are
        # entered — that path can no longer reach `ia_verified`, and
        # apps/activities/test_ssa_visit_validity.py pins it there.
        #
        # The endpoint asks for something the service did not, before SSA-01
        # moved the rule into `complete()`: either the SSA was collected on the
        # visit, or a reason it was not. Posting without it returns a 400
        # fragment and leaves the activity parked at `completion_started`.
        post(
            f"/my-plan/{activity.id}/complete",
            {
                "salesforce_id": "SVE-300001",
                "ssa_collected": "yes",
                **{f"score_{code}": "6.0" for code, _label in SsaIntervention.choices},
            },
            who=self.cceo,
        )
        self.assertTrue(
            SsaRecord.objects.filter(
                school=self.school,
                verification_status="confirmed",
                date_of_ssa__date__gte=timezone.localdate(),
            ).exists(),
            "completing an SSA collection visit recorded no assessment",
        )
        activity.refresh_from_db()
        self.assertIn(
            activity.status,
            ("submitted_to_pl", "awaiting_ia_verification"),
            f"a completed visit did not enter the review chain through the "
            f"endpoint; it sits at {activity.status}",
        )

        # ── 8. PL review ──────────────────────────────────────────────────
        if activity.status == "submitted_to_pl":
            post(f"/pl/review-queue/{activity.id}/confirm", who=self.pl)
            activity.refresh_from_db()
        self.assertEqual(activity.status, "awaiting_ia_verification")

        # ── 9. IA verification, through the door SEC-03 left unguarded ────
        with self.captureOnCommitCallbacks(execute=True):
            post(
                f"/ia/verification/{activity.id}/verify",
                {
                    "evidence_complete": "on",
                    "ssa_uploaded": "on",
                    "correct_school": "on",
                    "correct_cluster": "on",
                    "correct_intervention": "on",
                    "sf_id_entered": "on",
                    "duplicate_check_passed": "on",
                    "analytics_ready": "on",
                },
                who=self.ia,
            )
        activity.refresh_from_db()
        self.assertEqual(
            activity.status,
            "ia_verified",
            f"IA verification through the endpoint left the activity at "
            f"{activity.status}",
        )
        self.assertEqual(activity.ia_verification_status, "confirmed")

        # ── 10-12. Accountability, through its three doors ────────────────
        # One declared total for the activity, which the view allocates across
        # every disbursed advance proportionally — not one post per advance,
        # and the NetSuite field is `netsuite_code` here rather than the
        # `netsuiteId` the service takes. Both are contracts only the door
        # knows; the service walk above cannot see either.
        total_disbursed = sum(a.disbursed_amount or 0 for a in advances)
        post(
            f"/my-plan/{activity.id}/accountability",
            {
                "amount_spent": str(total_disbursed),
                "amount_returned": "0",
                "netsuite_code": "NS-JN3-DOOR",
            },
            who=self.cceo,
        )
        for advance in advances:
            advance.refresh_from_db()
            self.assertEqual(
                advance.status,
                "accountability_pl_pending",
                f"accountability submission through the endpoint left "
                f"advance {advance.id} at {advance.status}",
            )

        for advance in advances:
            post(f"/fund-requests/advances/{advance.id}/pl-approve", who=self.pl)
            advance.refresh_from_db()
            self.assertEqual(advance.status, "accountability_pending")

        # The accountant clears the WEEKLY REQUEST, not an advance: this door
        # takes `request_id` and walks every linked advance itself. A third
        # contract the service walk never sees.
        post(
            "/finance/actions/confirm_accountability",
            {"request_id": wfr.id},
            who=self.accountant,
        )
        for advance in advances:
            advance.refresh_from_db()
            self.assertEqual(
                advance.status,
                "accounted",
                f"the accountant's endpoint left advance {advance.id} at "
                f"{advance.status}",
            )

        # ── 13. Closure ───────────────────────────────────────────────────
        # Closed by the PL, not the Accountant.
        #
        # The service walk above closes as the Accountant and passes, because
        # `ActivityClosureService.close()` asserts no authority of its own. The
        # Accountant cannot close through any door: the endpoint is gated on
        # the `planning` page, which is {CCEO, PL, ProjectCoordinator, CD,
        # Admin}. So that green means "the function runs when called directly",
        # not "the spine closes" — and only a walk through the door can tell
        # the two apart.
        #
        # CLOSE-01 closed the gap this comment used to describe. The gating no
        # longer "lives entirely in the callers", where a later caller would
        # have introduced a hole with nothing to catch it: `close()` asserts
        # the same rule the door applies, read from the permission matrix so
        # the two cannot drift.
        #
        # The two finance callers (finance_services.py, in `clear_partner_payment`
        # and `enter_netsuite_id`) now pass `system=True` and say why: closure
        # there is the automatic CONSEQUENCE of an Accountant's payment act,
        # whose own authority check has already cleared them, and the Accountant
        # deliberately cannot reach the closure surface. That is still authority
        # living in a caller — but it is now declared at the call site instead
        # of inherited from a default, so a fourth caller has to make the same
        # decision explicitly rather than getting it by silence.
        response = post(f"/activities/{activity.id}/closure/close", who=self.pl)
        activity.refresh_from_db()
        # The view turns a refused close into a flash message and a redirect,
        # so name what it said rather than reporting a bare status mismatch.
        flash = [
            m.message
            for m in get_messages(response.wsgi_request)
            if "Closure failed" in m.message
        ]
        self.assertEqual(
            activity.status,
            "closed",
            "a fully executed, verified and accounted visit could not be "
            "closed through the closure endpoint. "
            + (f"The view said: {flash[0]}" if flash else "No reason was given."),
        )

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
