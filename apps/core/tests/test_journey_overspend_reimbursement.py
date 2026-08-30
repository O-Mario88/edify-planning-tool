"""Journey 7 — Fund overspending and reimbursement, walked end to end.

Journey 7 of the mandate's twenty-two: Advance, Actual spend exceeds advance,
Accountability, Reimbursement request, Approval, Payment, Final
reconciliation. It is the platform's only path where money leaves the
organisation a SECOND time for the same activity, which puts it squarely on
the mandate's "wrong payment" and "duplicate payment" P0 list.

FIN-02 fixed one edge of it — `reimburse()` used to take any integer verbatim,
pay it out, and only meet the settlement identity at
`confirm_reimbursement_receipt()`, which is the sole exit from
REIMBURSEMENT_DISBURSED and has no reversal. A mistyped figure moved real money
AND stranded the record for ever. That fix has a test. What had no test was the
whole path: that a genuine over-spend actually reaches the reimbursement
pipeline rather than clearing silently, that the second payment settles, and
that the ORIGINAL advance's figures survive it intact.

That last one matters more than it looks. The settlement identity is
`accounted == disbursed - returned + reimbursed`. If the reimbursement wrote
over `disbursed_amount` — the natural mistake, since both are "money we sent" —
the identity would still balance while the record silently lost what the first
disbursement was. This walks far enough to assert it did not.
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

TRANSPORT = 50_000
LUNCH = 12_000
OVERSPEND = 9_000


def _confirmed_ssa(school, *, fy=None, score=6.0):
    from apps.core.enums import SsaIntervention
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


def _schedulable_date() -> datetime.date:
    from apps.core.calendar_policy import SchedulingPolicyService

    day = timezone.localdate() + datetime.timedelta(days=7)
    for _ in range(21):
        if SchedulingPolicyService.check(None, day)["status"] != "blocked":
            return day
        day += datetime.timedelta(days=1)
    raise AssertionError("no schedulable date within three weeks")


def _at(day: datetime.date):
    return timezone.make_aware(datetime.datetime.combine(day, datetime.time(9, 0)))


class OverspendReimbursementJourneyTest(TestCase):
    """Advance → over-spend → accountability → reimburse → reconcile."""

    @classmethod
    def setUpTestData(cls):
        cls.region = Region.objects.create(name="Overspend Region")
        cls.district = District.objects.create(
            name="Overspend District", region=cls.region, district_type="primary"
        )
        cls.school = School.objects.create(
            school_id="SCH-OVER-1",
            name="Overspend Primary",
            region=cls.region,
            district=cls.district,
            school_type="client",
        )
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
                user=user, staff_number=f"OV-{name[:6]}", country="Uganda", title=role
            )
            return user, profile

        cls.cceo, cls.cceo_sp = _person("ov-cceo@edify.org", "Ov CCEO", "CCEO")
        cls.pl, cls.pl_sp = _person("ov-pl@edify.org", "Ov PL", "Program Lead")
        cls.ia, _ = _person("ov-ia@edify.org", "Ov IA", "ImpactAssessment")
        cls.accountant, _ = _person("ov-acct@edify.org", "Ov Acct", "Accountant")

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

    def _delivered_and_verified(self):
        """A real funded visit, executed and IA-verified — the state an
        over-spend claim must start from, because reimbursement is gated on
        IA confirming the work actually happened."""
        from apps.activities.ia_services import ActivityCertificationService
        from apps.activities.services import complete, start_completion
        from apps.activity_catalogue.services import resolve_item_for_workflow_kind
        from apps.evidence.models import EvidenceRecord
        from apps.fund_requests.weekly_service import (
            approve_weekly_request,
            confirm_receipt,
            disburse,
            request_advance,
        )
        from apps.planning.services import schedule_school_visit

        item = resolve_item_for_workflow_kind("school_visit")
        schedule_school_visit(
            {
                "schoolId": self.school.school_id,
                "catalogueItemId": item.id,
                "scheduledDate": _at(self.day).isoformat(),
                "activityPurposeText": "Journey 7 proof",
            },
            self.cceo,
        )
        activity = Activity.objects.get(school=self.school)

        wfr = WeeklyFundRequest.objects.get(responsible_user=self.cceo.id)
        request_advance(wfr.id, self.cceo)
        approve_weekly_request(wfr.id, self.pl)
        disburse(wfr.id, {"method": "Bank", "reference": "OV-1"}, self.accountant)
        confirm_receipt(wfr.id, self.cceo, bank_message_received=True)

        start_completion(activity.id, {}, self.cceo)
        EvidenceRecord.objects.create(
            activity_id=activity.id,
            kind="school_visit_form",
            uri="journey/over-form.pdf",
            original_name="over-form.pdf",
            file_size=2048,
            uploaded_by=self.cceo.id,
        )
        complete(activity.id, {"salesforceId": "SVE-700001"}, self.cceo)
        activity.refresh_from_db()
        if activity.status == "submitted_to_pl":
            from apps.pl_review.services import confirm as pl_confirm

            pl_confirm(activity.id, self.pl)
            activity.refresh_from_db()
        with self.captureOnCommitCallbacks(execute=True):
            ActivityCertificationService.certify_activity(activity, {}, str(self.ia.id))
        activity.refresh_from_db()
        self.assertEqual(activity.ia_verification_status, "confirmed")

        advances = list(
            AdvanceRequest.objects.filter(
                budget_line__weekly_request_lines__weekly_fund_request=wfr
            ).distinct()
        )
        self.assertTrue(advances, "no advance was disbursed to over-spend against")
        return activity, advances

    def test_an_overspend_is_reimbursed_and_the_advance_still_reconciles(self):
        from apps.fund_requests import advance_service

        _activity, advances = self._delivered_and_verified()

        for index, advance in enumerate(advances):
            advance.refresh_from_db()
            original_disbursed = advance.disbursed_amount
            original_reference = advance.disburse_reference
            self.assertGreater(original_disbursed, 0)

            # ── 2. Actual spend exceeds the advance ───────────────────────
            spent = original_disbursed + OVERSPEND
            advance_service.submit_accountability(
                advance.id,
                {"amountSpent": spent, "netsuiteId": f"NS-OVER-{index}"},
                self.cceo,
            )

            # ── 3. Accountability routes through the PL ───────────────────
            advance_service.pl_approve_accountability(advance.id, self.pl)
            advance.refresh_from_db()
            self.assertEqual(advance.status, "accountability_pending")

            # ── 4. The over-spend becomes a reimbursement claim ───────────
            # The branch that matters: an over-spend must NOT clear as though
            # it were settled. It has to enter the pipeline where a second
            # payment is authorised deliberately.
            advance_service.approve_accountability(advance.id, self.accountant)
            advance.refresh_from_db()
            self.assertEqual(
                advance.status,
                "reimbursement_submitted",
                "an over-spent advance cleared without ever raising a "
                "reimbursement claim — the employee is out of pocket and the "
                "record says settled",
            )

            # ── 5 & 6. Approval and payment ───────────────────────────────
            advance_service.reimburse(
                advance.id,
                {"method": "Bank", "reference": f"RMB-{index}"},
                self.accountant,
            )
            advance.refresh_from_db()
            self.assertEqual(advance.status, "reimbursement_disbursed")
            self.assertEqual(
                advance.reimbursed_amount,
                OVERSPEND,
                "the reimbursement paid something other than the variance",
            )

            # The original advance's own figures must survive the second
            # payment untouched. Both are "money we sent"; writing one over
            # the other would keep the identity balanced while losing what the
            # first disbursement was.
            self.assertEqual(
                advance.disbursed_amount,
                original_disbursed,
                "reimbursing overwrote the original disbursed amount",
            )
            self.assertEqual(
                advance.disburse_reference,
                original_reference,
                "reimbursing overwrote the original disbursement reference",
            )

            # ── 7. Final reconciliation ───────────────────────────────────
            advance_service.confirm_reimbursement_receipt(advance.id, {}, self.cceo)
            advance.refresh_from_db()
            self.assertEqual(
                advance.status,
                "reimbursed",
                f"advance {advance.id} stalled at {advance.status} — the "
                "over-spend never reached a settled state",
            )
            self.assertEqual(
                advance.accounted_amount,
                advance.disbursed_amount
                - (advance.returned_amount or 0)
                + advance.reimbursed_amount,
                "the settlement identity does not hold at the terminal state",
            )

    def test_the_same_overspend_walks_the_real_endpoints(self):
        """JRN-01: the same money path, driven through the platform's own doors.

        The test above proves the *services* move an over-spend correctly. It
        proves nothing about the layer a real user touches, and until JRN-01
        was found no mandated journey did — the traceability matrix recorded an
        empty route column for all twenty. The gap matters most here, because
        this is the platform's only path where money leaves the organisation a
        second time for the same activity.

        The five steps are the five real endpoints, and between them they
        exercise both guard families: four DRF views behind
        ``RequirePermissions`` (accountability at ``planning.view``, the PL's
        approval at ``budget.approve``, both accountant acts at
        ``payment.act``), and one page view behind
        ``@require_page_permission("my_plan")`` that also runs an object-level
        ``can_view_record`` check before it will settle anything.

        Splitting the money acts across ``budget.approve`` and ``payment.act``
        is the separation of duties this journey rests on. Driving it over HTTP
        is what proves the views hand the services the principal those
        permissions were checked against — not merely that each layer is
        correct alone, which was exactly the shape of SEC-01.
        """
        import json

        activity, advances = self._delivered_and_verified()
        advance = advances[0]
        advance.refresh_from_db()
        original_disbursed = advance.disbursed_amount
        original_reference = advance.disburse_reference
        self.assertGreater(original_disbursed, 0)

        def post_json(path, payload, actor):
            self.client.force_login(actor)
            try:
                return self.client.post(
                    path, data=json.dumps(payload), content_type="application/json"
                )
            finally:
                self.client.logout()

        base = f"/api/fund-requests/advances/{advance.id}"

        # ── 2-3. Over-spend declared, and routed through the PL ───────────
        response = post_json(
            f"{base}/account",
            {
                "amountSpent": original_disbursed + OVERSPEND,
                "netsuiteId": "NS-OVER-HTTP",
            },
            self.cceo,
        )
        self.assertEqual(response.status_code, 200, response.content[:400])

        response = post_json(f"{base}/pl-approve", {}, self.pl)
        self.assertEqual(response.status_code, 200, response.content[:400])
        advance.refresh_from_db()
        self.assertEqual(advance.status, "accountability_pending")

        # ── 4. The over-spend becomes a claim, not a silent clearance ─────
        response = post_json(f"{base}/account-approve", {}, self.accountant)
        self.assertEqual(response.status_code, 200, response.content[:400])
        advance.refresh_from_db()
        self.assertEqual(
            advance.status,
            "reimbursement_submitted",
            "driven through the real endpoint, an over-spent advance cleared "
            "without raising a claim",
        )

        # ── 5-6. The second payment ───────────────────────────────────────
        response = post_json(
            f"{base}/reimburse",
            {"method": "Bank", "reference": "RMB-HTTP"},
            self.accountant,
        )
        self.assertEqual(response.status_code, 200, response.content[:400])
        advance.refresh_from_db()
        self.assertEqual(advance.status, "reimbursement_disbursed")
        self.assertEqual(advance.reimbursed_amount, OVERSPEND)

        # ── 7. The employee's own receipt confirmation ────────────────────
        # A page view rather than an API one: page gate, then an object-level
        # can_view_record check, then the service.
        self.client.force_login(self.cceo)
        try:
            response = self.client.post(
                f"/my-plan/{activity.id}/confirm-reimbursement-receipt", {}
            )
        finally:
            self.client.logout()
        self.assertEqual(response.status_code, 200, response.content[:400])

        advance.refresh_from_db()
        self.assertEqual(
            advance.status,
            "reimbursed",
            "the over-spend never reached a settled state through the doors a "
            "real user actually uses",
        )
        self.assertEqual(
            advance.accounted_amount,
            advance.disbursed_amount
            - (advance.returned_amount or 0)
            + advance.reimbursed_amount,
            "the settlement identity does not hold at the terminal state",
        )
        self.assertEqual(
            advance.disbursed_amount,
            original_disbursed,
            "reimbursing through the endpoint overwrote the original disbursed "
            "amount",
        )
        self.assertEqual(
            advance.disburse_reference,
            original_reference,
            "reimbursing through the endpoint overwrote the original "
            "disbursement reference",
        )

    def test_the_money_doors_refuse_at_whichever_layer_owns_the_rule(self):
        """The doors above must be shut — and they are shut in two ways.

        A walk that only drives the happy path proves the endpoints exist, not
        that they are guarded, and an unguarded route on *this* journey
        releases a second payment. So each money act is also attempted by
        someone who must not complete it.

        What this test has to get right, and what a status-code-only sweep gets
        wrong, is that the platform answers at two different layers:

        * ``payment.act`` is held by the Accountant alone, so the CCEO and the
          Programme Lead are stopped **at the door** with a 403 on both
          accountant acts.
        * ``budget.approve`` is held by the CCEO *and* the Programme Lead, so
          the CCEO passes the door at ``pl-approve`` and is stopped **by the
          service**, which refuses self-approval. Demanding a 403 there would
          report a working separation of duties as a security hole.

        So the door probes assert 403 and the service probe asserts the money
        did not move. The second assertion is the stronger one in both cases,
        and it is applied to all of them: a refusal that still advances the
        record is not a refusal.
        """
        _activity, advances = self._delivered_and_verified()
        advance = advances[0]
        advance.refresh_from_db()
        status_before = advance.status
        base = f"/api/fund-requests/advances/{advance.id}"

        def post_as(path, actor):
            self.client.force_login(actor)
            try:
                return self.client.post(path, {})
            finally:
                self.client.logout()

        # ── Refused at the door: neither role holds payment.act ───────────
        for act, path in (
            ("the accountant's approval", f"{base}/account-approve"),
            ("the second payment", f"{base}/reimburse"),
        ):
            for actor in (self.cceo, self.pl):
                with self.subTest(door=path, actor=actor.email):
                    response = post_as(path, actor)
                    self.assertEqual(
                        response.status_code,
                        403,
                        f"{actor.email} reached {act} at {path}. On this "
                        "journey an unguarded route releases money a second "
                        "time.",
                    )

        # ── Admitted at the door, refused by the service ──────────────────
        # The CCEO holds budget.approve, so the gate lets them through and the
        # self-approval rule stops them. The platform's HTMX actions render
        # such a refusal in the page body rather than as a status, so the only
        # assertion that means anything here is whether the record moved.
        post_as(f"{base}/pl-approve", self.cceo)

        advance.refresh_from_db()
        self.assertEqual(
            advance.status,
            status_before,
            "a refused attempt still advanced the advance. Whichever layer "
            "owns the rule, a refusal that moves the record is not a refusal.",
        )
        self.assertFalse(
            advance.reimbursed_amount,
            "money was reimbursed by a request that should have been refused",
        )

    def test_the_claim_cannot_be_paid_twice(self):
        """Duplicate payment is on the mandate's P0 list by name."""
        from apps.core.exceptions import BadRequest
        from apps.fund_requests import advance_service

        _activity, advances = self._delivered_and_verified()
        advance = advances[0]
        advance.refresh_from_db()

        advance_service.submit_accountability(
            advance.id,
            {
                "amountSpent": advance.disbursed_amount + OVERSPEND,
                "netsuiteId": "NS-TWICE-1",
            },
            self.cceo,
        )
        advance_service.pl_approve_accountability(advance.id, self.pl)
        advance_service.approve_accountability(advance.id, self.accountant)
        advance_service.reimburse(
            advance.id, {"method": "Bank", "reference": "RMB-A"}, self.accountant
        )
        advance.refresh_from_db()
        paid_once = advance.reimbursed_amount

        with self.assertRaises(BadRequest):
            advance_service.reimburse(
                advance.id, {"method": "Bank", "reference": "RMB-B"}, self.accountant
            )
        advance.refresh_from_db()
        self.assertEqual(
            advance.reimbursed_amount,
            paid_once,
            "a second reimbursement call changed the paid figure",
        )
