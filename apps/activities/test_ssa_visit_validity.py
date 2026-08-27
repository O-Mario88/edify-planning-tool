"""SSA-01 — an SSA visit is only valid work once the scores are entered.

The product rule, in the programme owner's words: "the ssa support visits is
only considered valid if the ssa scores are entered." A CCEO who arrives to
find the school shut can still CLOSE THE VISIT OUT by giving a reason, so the
record stays honest and the work is not stuck in their queue. What they cannot
do is have it certified: IA verification refuses it, it never counts toward
SSA targets, and it never feeds the improvement analytics. It reads as
done-but-unverified.

Both halves of that rule were missing, in the same shape this audit keeps
finding — a rule written on one door only.

  * ASKING. The web completion form refused a completion that answered
    neither "here are the scores" nor "here is why there are none". It lived
    only there. The same act has a second door, `POST /api/activities/<id>/
    complete`, generated from `complete()` by the `_action_view` factory, and
    that one never asked. Measured before the fix: an activity with
    `ssa_collection_expected=True` completed through the API returned 200,
    advanced to `submitted_to_pl`, then verified to `ia_verified` with
    `ssa_not_collected_reason` still None — counted and reported, with nobody
    having answered the question.

  * REFUSING. `SSAValidationService.validate_ssa` looked like the gate but was
    a RECOMMENDATION: `get_verification_checks` puts its result into the dict
    that prepopulates the IA's checklist, and the form submits fine with the
    box ticked over it. Advisory, not a gate.

These tests hold both doors on both halves. The last one is the anti-vacuity
check: a visit that DID collect its scores must still verify, or the gate
could be hard-wired to refuse and every other test here would still pass.
"""

from __future__ import annotations

import datetime

from django.test import TestCase
from django.utils import timezone

from apps.accounts.models import StaffProfile, User
from apps.activities import services
from apps.activities.ia_services import ActivityCertificationService
from apps.activities.models import Activity
from apps.core.enums import SsaIntervention
from apps.core.exceptions import BadRequest
from apps.core.fy import get_operational_fy
from apps.evidence.models import EvidenceRecord
from apps.geography.models import District, Region
from apps.schools.models import School
from apps.ssa.models import SsaRecord, SsaScore


class SsaVisitValidity(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.region = Region.objects.create(name="SSA-01 Region")
        cls.district = District.objects.create(
            name="SSA-01 District", region=cls.region, district_type="primary"
        )
        cls.school = School.objects.create(
            school_id="SSA01-001",
            name="SSA-01 School",
            region=cls.region,
            district=cls.district,
            school_type="core",
            enrollment=200,
        )
        cls.cceo = User.objects.create_user(
            email="ssa01-cceo@edify.org",
            name="SSA-01 CCEO",
            roles=["CCEO"],
            active_role="CCEO",
            password="x",
            is_active=True,
        )
        cls.cceo_staff = StaffProfile.objects.create(
            user=cls.cceo, staff_number="ST-SSA01-CCEO", country="Uganda"
        )
        cls.ia_user = User.objects.create_user(
            email="ssa01-ia@edify.org",
            name="SSA-01 IA",
            roles=["ImpactAssessment"],
            active_role="ImpactAssessment",
            password="x",
            is_active=True,
        )
        StaffProfile.objects.create(
            user=cls.ia_user, staff_number="ST-SSA01-IA", country="Uganda"
        )

    # ------------------------------------------------------------------ setup

    def _visit(self, *, status="completion_started", expects_ssa=True, reason=None):
        """A visit whose purpose is SSA collection, ready for its next step."""
        activity = Activity.objects.create(
            school=self.school,
            activity_type="core_visit",
            status=status,
            fy=get_operational_fy(),
            planned_date=self.visit_date,
            actual_delivery_date=self.visit_date,
            focus_intervention="leadership",
            salesforce_activity_id=self.sf_id,
            responsible_staff_id=str(self.cceo_staff.id),
            ssa_collection_expected=expects_ssa,
            ssa_not_collected_reason=reason,
            teachers_attended=4,
            leaders_attended=1,
        )
        EvidenceRecord.objects.create(
            activity_id=activity.id,
            kind="photo",
            uri="ssa01-evidence.jpg",
            uploaded_by=str(self.cceo_staff.id),
            quarantined=False,
        )
        return activity

    def setUp(self):
        self.visit_date = timezone.localdate() - datetime.timedelta(days=3)
        # Unique per test: reserve_salesforce_id enforces global uniqueness.
        case = self.id().rsplit(".", 1)[-1].replace("_", "-").upper()
        self.sf_id = f"SVE-SSA01-{case[:40]}"

    def _record_scores(self, *, on, status="confirmed", fy=None, school=None):
        """The scores the visit went to collect, dated the day they were taken."""
        record = SsaRecord.objects.create(
            school=school or self.school,
            fy=fy or get_operational_fy(),
            date_of_ssa=timezone.make_aware(
                datetime.datetime.combine(on, datetime.time())
            ),
            average_score=6.0,
            verification_status=status,
        )
        for intervention, _label in SsaIntervention.choices:
            SsaScore.objects.create(
                ssa_record=record, intervention=intervention, score=6.0
            )
        return record

    def _client_school_visit(self):
        """An SSA visit that the older Core-only rule does not cover.

        `_confirm_activity_after_authorization`'s strict validation fires only
        for `activity_type in ("core_visit", "core_training")` AND
        `school.school_type == "core"`. Everything set up here fails both
        conditions on purpose, so whatever refuses this activity can only be
        the SSA-01 gate.
        """
        school = School.objects.create(
            school_id=f"SSA01-CLIENT-{self.id().rsplit('.', 1)[-1][:12]}",
            name="SSA-01 Client School",
            region=self.region,
            district=self.district,
            school_type="client",
            enrollment=180,
        )
        activity = self._visit(
            status="awaiting_ia_verification", reason="School closed for a funeral."
        )
        activity.school = school
        activity.activity_type = "school_visit"
        activity.save(update_fields=["school", "activity_type"])
        return school, activity

    # --------------------------------------------------------- asking (door 2)

    def test_the_api_completion_door_asks_the_ssa_question(self):
        """`complete()` is the domain act behind BOTH the web form and the
        generated `/api/activities/<id>/complete` route. The rule has to live
        here, or the API door keeps its own laxer standard."""
        activity = self._visit()

        with self.assertRaises(BadRequest) as caught:
            services.complete(str(activity.id), {"salesforceId": self.sf_id}, self.cceo)

        self.assertIn("ssa", str(caught.exception).lower())
        activity.refresh_from_db()
        self.assertEqual(
            activity.status,
            "completion_started",
            "An SSA visit completed without answering the SSA question.",
        )

    def test_a_visit_that_never_expected_an_ssa_is_untouched(self):
        """Scoped exactly as the form scopes it. Ordinary support visits,
        partner work and the in-school training pair must pass through."""
        activity = self._visit(expects_ssa=False)

        services.complete(str(activity.id), {"salesforceId": self.sf_id}, self.cceo)

        activity.refresh_from_db()
        self.assertNotEqual(activity.status, "completion_started")

    def test_a_reason_lets_the_cceo_close_the_visit_out(self):
        """The school was shut. The work must not be stuck in their queue."""
        activity = self._visit()

        services.complete(
            str(activity.id),
            {
                "salesforceId": self.sf_id,
                "ssaNotCollectedReason": "School closed for a funeral.",
            },
            self.cceo,
        )

        activity.refresh_from_db()
        self.assertNotEqual(
            activity.status,
            "completion_started",
            "A CCEO who gave a reason could not close the visit out.",
        )

    # ------------------------------------------------------ refusing (2 doors)

    def test_ia_cannot_certify_a_visit_that_collected_no_scores(self):
        """The live IA workspace door
        (`ActivityCertificationService.certify_activity`)."""
        activity = self._visit(
            status="awaiting_ia_verification", reason="School closed for a funeral."
        )

        with self.assertRaises(BadRequest) as caught:
            ActivityCertificationService.certify_activity(
                activity, {}, str(self.ia_user.id)
            )

        self.assertIn("ssa", str(caught.exception).lower())
        activity.refresh_from_db()
        self.assertEqual(activity.status, "awaiting_ia_verification")

    def test_the_service_door_refuses_it_too(self):
        """`ia_confirm` — SSA-01 exists BECAUSE a rule was written on one door
        only, so fixing it on one door would just move the hole.

        DEFENCE IN DEPTH, not sole coverage. Mutation-checked: removing the new
        gate does NOT fail this test, because `_confirm_activity_after_
        authorization` already refused a CORE-typed visit to a CORE school with
        no confirmed record. That older rule is narrow — it fires only for
        `activity_type in ("core_visit", "core_training")` AND
        `school.school_type == "core"` — so it leaves the two cases pinned
        below. This test exists so the pair of rules cannot BOTH be removed
        without something going red."""
        activity = self._visit(
            status="awaiting_ia_verification", reason="School closed for a funeral."
        )

        with self.assertRaises(BadRequest) as caught:
            services.ia_confirm(str(activity.id), {}, self.ia_user)

        self.assertIn("ssa", str(caught.exception).lower())
        activity.refresh_from_db()
        self.assertEqual(activity.status, "awaiting_ia_verification")

    def test_last_years_assessment_does_not_make_this_visit_valid(self):
        """`latest_applicable_record` has no date scoping and `SsaRecord` has
        no FK to Activity, so without the FY scope the school's previous
        assessment would satisfy a visit that collected nothing — precisely
        the case the rule exists to catch."""
        activity = self._visit(
            status="awaiting_ia_verification", reason="School closed for a funeral."
        )
        last_fy = str(int(get_operational_fy()) - 1)
        self._record_scores(
            on=self.visit_date - datetime.timedelta(days=400), fy=last_fy
        )

        with self.assertRaises(BadRequest):
            services.ia_confirm(str(activity.id), {}, self.ia_user)

    def test_an_unconfirmed_upload_does_not_make_it_valid_either(self):
        """Same rule as `latest_applicable_record`'s own docstring: an
        unverified upload must never satisfy a verification gate.

        Also defence in depth on this door for a Core school — the older rule
        reaches the same conclusion here. The new gate is what carries it for
        every other school type; see the client-school test below."""
        activity = self._visit(
            status="awaiting_ia_verification", reason="School closed for a funeral."
        )
        self._record_scores(on=self.visit_date, status="pending")

        with self.assertRaises(BadRequest):
            services.ia_confirm(str(activity.id), {}, self.ia_user)

    def test_an_ssa_visit_to_a_client_school_is_gated_too(self):
        """The widest part of the hole, and the part with no older rule
        underneath it.

        `_confirm_activity_after_authorization`'s strict Core validation fires
        only for `activity_type in ("core_visit", "core_training")` AND
        `school.school_type == "core"`. An ordinary `school_visit` to a CLIENT
        school, scheduled to collect an SSA, matched neither condition — so
        before this gate, NOTHING on either verification door asked whether the
        scores existed. Mutation-checked: this test is the one that goes red
        when the new gate is removed from the service door."""
        school, activity = self._client_school_visit()

        with self.assertRaises(BadRequest) as caught:
            services.ia_confirm(str(activity.id), {}, self.ia_user)

        self.assertIn("ssa", str(caught.exception).lower())
        activity.refresh_from_db()
        self.assertEqual(
            activity.status,
            "awaiting_ia_verification",
            "An SSA visit to a non-Core school verified with no scores.",
        )

    def test_an_unconfirmed_upload_at_a_client_school_is_refused(self):
        """The confirmed-only half of the gate, pinned where no older rule
        overlaps it.

        Mutation-checked: dropping `verification_status="confirmed"` from the
        gate used to break nothing, because the Core-school test above was
        caught by `latest_applicable_record` inside the older rule instead.
        On a client school there is no older rule, so this test is the only
        thing standing between an unverified upload and a certified visit —
        which is exactly what `latest_applicable_record`'s docstring says must
        never happen."""
        school, activity = self._client_school_visit()
        self._record_scores(on=self.visit_date, status="pending", school=school)

        with self.assertRaises(BadRequest) as caught:
            services.ia_confirm(str(activity.id), {}, self.ia_user)

        self.assertIn("ssa", str(caught.exception).lower())
        activity.refresh_from_db()
        self.assertEqual(activity.status, "awaiting_ia_verification")

    def test_a_confirmed_upload_at_a_client_school_verifies(self):
        """Anti-vacuity for the pair above: the client-school path must still
        pass on real data, or both tests would survive a gate hard-wired to
        refuse every non-Core visit."""
        school, activity = self._client_school_visit()
        self._record_scores(on=self.visit_date, school=school)

        services.ia_confirm(str(activity.id), {}, self.ia_user)

        activity.refresh_from_db()
        self.assertEqual(activity.status, "ia_verified")

    # ------------------------------------------------------------ anti-vacuity

    def test_a_visit_that_did_collect_its_scores_verifies_normally(self):
        """Without this, the gate could be hard-wired to refuse and every
        test above would still pass."""
        activity = self._visit(status="awaiting_ia_verification")
        self._record_scores(on=self.visit_date)

        services.ia_confirm(str(activity.id), {}, self.ia_user)

        activity.refresh_from_db()
        self.assertEqual(
            activity.status,
            "ia_verified",
            "A visit that collected its scores on the day could not be verified.",
        )
