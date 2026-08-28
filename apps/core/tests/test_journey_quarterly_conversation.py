"""Journey 10 — the quarterly performance conversation, walked end to end.

Seven steps: HR unlocks, Employee evaluates, Manager evaluates, Automatic
values stay read-only, HR oversight, Close, Snapshot lock.

Two of those seven are not steps at all. "Automatic values stay read-only" and
"Snapshot lock" are properties the other five must hold while they run, and
they are the whole reason this journey is on the mandate's list. A performance
conversation where the measured figure can be typed over is a conversation
about someone's opinion wearing a number's clothes, and one where the figure
moves between the manager writing their assessment and the employee reading it
is a conversation about two different quarters.

So this walk drives the five steps in order and, at each one, asks the two
questions the mandate cares about: can anyone write the computed channel, and
has the frozen figure moved. The most useful assertion in the file is the one
where real verified work lands AFTER HR opens the window: `live_progress` moves
because the work is genuinely done, the snapshot does not because the meeting
is already underway, and both of those are correct at the same time.

The authority rules are walked as refusals rather than asserted as a table.
Every one of them is an inversion somebody could reasonably have got backwards:
the employee is the only person who may write the reflection AND the only
person who may acknowledge, and is barred from every assessing action in
between; HR governs the window and calibration but may not write the manager's
judgement, which is a separation this codebase says it lost once already —
"This used to accept HR as an alternative assessor, so a governance role could
write the manager's judgment on the manager's behalf."
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
from apps.core.exceptions import BadRequest, Forbidden
from apps.core.fy import get_operational_fy
from apps.geography.models import District, Region
from apps.hr.models import (
    PerformanceCycle,
    PerformanceSnapshot,
    PriorityAccountability,
    ReviewStage,
    StrategicPriority,
    StrategicPriorityLevel,
    StrategicPriorityRoleRule,
)
from apps.schools.models import School

TRANSPORT = 50_000
ANNUAL_VISITS = 12


class _Principal:
    """What the HR services read off a caller.

    `staff_profile` matters and is easy to leave off: `visible_reviews` scopes
    HR and the Country Director by `principal.staff_profile.country`, so a
    principal without one sees no reviews at all and every HR action refuses
    with an access error that looks like an authority bug.
    """

    def __init__(self, user, profile=None):
        self.id = user.id
        self.user_id = user.id
        self.active_role = user.active_role
        self.staff_profile = profile
        self.staff_profile_id = profile.id if profile else None


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


def _next_schedulable(start: datetime.date, offset_days: int) -> datetime.date:
    """The first schedulable day at least `offset_days` after `start`."""
    from apps.core.calendar_policy import SchedulingPolicyService

    if not offset_days:
        return start
    day = start + datetime.timedelta(days=offset_days)
    for _ in range(21):
        if SchedulingPolicyService.check(None, day)["status"] != "blocked":
            return day
        day += datetime.timedelta(days=1)
    raise AssertionError("no schedulable date within three weeks of the offset")


def _at(day: datetime.date):
    return timezone.make_aware(datetime.datetime.combine(day, datetime.time(9, 0)))


class QuarterlyConversationJourneyTest(TestCase):
    """Window opened → reflection → assessment → calibration → acknowledged."""

    @classmethod
    def setUpTestData(cls):
        cls.region = Region.objects.create(name="Quarterly Region")
        cls.district = District.objects.create(
            name="Quarterly District", region=cls.region, district_type="primary"
        )
        cls.school = School.objects.create(
            school_id="SCH-QTR-1",
            name="Quarterly Primary",
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
                user=user, staff_number=f"QT-{name[:6]}", country="Uganda", title=role
            )
            return user, profile

        cls.rvp, cls.rvp_sp = _person(
            "qt-rvp@edify.org", "Qt RVP", "RegionalVicePresident"
        )
        cls.cd, cls.cd_sp = _person("qt-cd@edify.org", "Qt CD", "CountryDirector")
        cls.hr, cls.hr_sp = _person("qt-hr@edify.org", "Qt HR", "HumanResources")
        cls.cceo, cls.cceo_sp = _person("qt-cceo@edify.org", "Qt CCEO", "CCEO")
        cls.pl, cls.pl_sp = _person("qt-pl@edify.org", "Qt PL", "Program Lead")
        cls.ia, cls.ia_sp = _person("qt-ia@edify.org", "Qt IA", "ImpactAssessment")
        cls.accountant, cls.acct_sp = _person(
            "qt-acct@edify.org", "Qt Acct", "Accountant"
        )

        StaffSupervisorAssignment.objects.create(
            supervisor=cls.pl_sp, supervisee=cls.cceo_sp
        )
        StaffSchoolAssignment.objects.create(staff=cls.cceo_sp, school_id=cls.school.id)

        cls.day = _schedulable_date()
        cls.fy = get_operational_fy(cls.day)
        cls.catalogue, _ = CostCatalogue.objects.get_or_create(
            country="Uganda", fy=cls.fy, is_active=True, defaults={"version": 1}
        )
        CostSetting.objects.update_or_create(
            key="primary_transport_per_day",
            defaults={
                "label": "Primary Transport Per Day",
                "unit_cost": TRANSPORT,
                "fy": cls.fy,
                "catalogue": cls.catalogue,
            },
        )

    # ── Setting the stage: an agreed review to hold a conversation about ──
    def _agreed_review(self):
        from apps.hr import performance_service, priority_cascade

        priority = StrategicPriority.objects.create(
            fy=self.fy,
            level=StrategicPriorityLevel.REGIONAL,
            title="Every assigned school is visited and verified",
            strategic_purpose="Direct, evidenced contact with every school.",
            target_guidance="100% of assigned schools",
            weight_min=10,
            weight_max=40,
            is_mandatory=True,
        )
        StrategicPriorityRoleRule.objects.create(
            priority=priority,
            role="CCEO",
            accountability=PriorityAccountability.EXECUTE,
            metric_key="direct_visits",
            outcome_statement="I visit and evidence every school assigned to me.",
            default_weight=30,
        )
        priority_cascade.publish(priority, _Principal(self.rvp, self.rvp_sp))

        review = performance_service.open_cycle(
            self.cceo_sp,
            _Principal(self.hr, self.hr_sp),
            fy=self.fy,
            due_date=self.day + datetime.timedelta(days=180),
        )
        priority_cascade.apply_to_review(
            review, "CCEO", {"direct_visits": ANNUAL_VISITS}
        )
        cascaded = review.priorities.get()
        performance_service.set_priorities(
            review.id,
            _Principal(self.cceo, self.cceo_sp),
            [
                {
                    "id": cascaded.id,
                    "outcome_statement": cascaded.outcome_statement,
                    "metric_key": cascaded.metric_key,
                    "weight": 100,
                }
            ],
        )
        review.refresh_from_db()
        performance_service.agree_priorities(review.id, _Principal(self.pl, self.pl_sp))
        review.refresh_from_db()
        cycle, _ = PerformanceCycle.objects.get_or_create(fy=self.fy)
        return review, cycle

    def _verified_visit(self, purpose="Quarterly proof", *, offset_days=0):
        """One real, delivered, IA-verified school visit.

        `offset_days` moves the visit to another schedulable day. The platform
        refuses "an identical activity ... for this target on this date", which
        is right — two visits to one school on one day is a duplicate, not two
        visits — so a walk that needs a second one has to book it elsewhere in
        the calendar, and then find the weekly fund request for THAT week
        rather than the most recent row.
        """
        from apps.activities.ia_services import ActivityCertificationService
        from apps.activities.services import complete, start_completion
        from apps.activity_catalogue.services import resolve_item_for_workflow_kind
        from apps.evidence.models import EvidenceRecord
        from apps.fund_requests.models import WeeklyFundRequest
        from apps.fund_requests.weekly_service import (
            approve_weekly_request,
            confirm_receipt,
            disburse,
            request_advance,
        )
        from apps.planning.services import schedule_school_visit

        # INTG-07 put a uniqueness constraint on the Salesforce id, which is
        # the point of it — one Salesforce record, one activity. A walk that
        # completes two visits therefore needs two ids, and deriving them from
        # a cuid prefix does not work: ids minted in the same millisecond
        # share one.
        self._sf_seq = getattr(self, "_sf_seq", 300000) + 1
        day = _next_schedulable(self.day, offset_days)
        item = resolve_item_for_workflow_kind("school_visit")
        schedule_school_visit(
            {
                "schoolId": self.school.school_id,
                "catalogueItemId": item.id,
                "scheduledDate": _at(day).isoformat(),
                "activityPurposeText": purpose,
            },
            self.cceo,
        )
        activity = (
            Activity.objects.filter(school=self.school, scheduled_date__date=day)
            .order_by("-id")
            .first()
        )
        self.assertIsNotNone(activity, "the visit must actually have been scheduled")

        wfr = WeeklyFundRequest.objects.filter(
            responsible_user=self.cceo.id,
            week_start_date__lte=day,
            week_end_date__gte=day,
        ).first()
        self.assertIsNotNone(
            wfr, "the scheduled visit must have raised a weekly fund request"
        )
        request_advance(wfr.id, self.cceo)
        approve_weekly_request(wfr.id, self.pl)
        disburse(
            wfr.id,
            {"method": "Bank", "reference": f"QT-{self._sf_seq}"},
            self.accountant,
        )
        confirm_receipt(wfr.id, self.cceo)

        start_completion(activity.id, {}, self.cceo)
        EvidenceRecord.objects.create(
            activity_id=activity.id,
            kind="school_visit_form",
            uri=f"journey/{activity.id}.pdf",
            original_name="quarterly-form.pdf",
            file_size=2048,
            uploaded_by=self.cceo.id,
        )
        complete(activity.id, {"salesforceId": f"SVE-{self._sf_seq}"}, self.cceo)
        activity.refresh_from_db()
        if activity.status == "submitted_to_pl":
            from apps.pl_review.services import confirm as pl_confirm

            pl_confirm(activity.id, self.pl)
            activity.refresh_from_db()
        ActivityCertificationService.certify_activity(
            activity, {"decision": "verified"}, str(self.ia.id)
        )
        activity.refresh_from_db()
        return activity

    # ── Step 1: HR unlocks ───────────────────────────────────────────────
    def test_step_1_only_hr_may_open_the_window(self):
        from apps.hr.performance_engine import activate_window

        _, cycle = self._agreed_review()
        for actor in (self.pl, self.cd, self.cceo):
            with self.subTest(actor.active_role):
                with self.assertRaises(Forbidden):
                    activate_window(cycle, "q1", _Principal(actor))

        with self.assertRaises(BadRequest):
            activate_window(cycle, "not_a_quarter", _Principal(self.hr, self.hr_sp))

        self.assertEqual(
            PerformanceCycle.objects.get(id=cycle.id).active_window,
            "none",
            "a refused activation must not have opened the window anyway",
        )

    def test_step_1_opening_the_window_freezes_the_numbers(self):
        """Activation is the snapshot. That is the design, not a side effect."""
        from apps.hr.performance_engine import activate_window

        review, cycle = self._agreed_review()
        self._verified_visit()

        taken = activate_window(cycle, "q1", _Principal(self.hr, self.hr_sp))
        self.assertGreaterEqual(taken, 1)

        snapshot = PerformanceSnapshot.objects.get(review=review, window="q1")
        rows = snapshot.data["priorities"]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["metric_key"], "direct_visits")
        self.assertEqual(
            rows[0]["actual"],
            1,
            "the frozen figure must be the real one at the moment of freezing",
        )

    # ── Step 4 and 7, which is why this journey is on the list ───────────
    def test_the_frozen_figure_does_not_move_when_the_live_one_does(self):
        """The assertion this whole file exists for.

        Work delivered after HR opens the window is real work — `live_progress`
        must count it. The conversation being held this quarter must not
        change underneath the two people having it. Both are true at once, and
        a platform that cannot hold both is one where the manager and the
        employee are reading different numbers off the same screen.
        """
        from apps.hr.performance_engine import activate_window, live_progress

        review, cycle = self._agreed_review()
        self._verified_visit("Before the window opened")
        activate_window(cycle, "q1", _Principal(self.hr, self.hr_sp))

        frozen = PerformanceSnapshot.objects.get(review=review, window="q1")
        frozen_actual = frozen.data["priorities"][0]["actual"]

        self._verified_visit("After the window opened", offset_days=8)

        priority = review.priorities.get()
        self.assertEqual(
            live_progress(priority)["actual"],
            frozen_actual + 1,
            "genuinely verified work must move the live figure",
        )
        frozen.refresh_from_db()
        self.assertEqual(
            frozen.data["priorities"][0]["actual"],
            frozen_actual,
            "the snapshot the conversation is held against must not move "
            "while the conversation is underway",
        )

    def test_reopening_the_same_window_never_overwrites_its_snapshot(self):
        """Idempotent per window — 'that is the whole point'."""
        from apps.hr.performance_engine import activate_window, take_snapshot

        review, cycle = self._agreed_review()
        self._verified_visit("First")
        activate_window(cycle, "q1", _Principal(self.hr, self.hr_sp))
        original = PerformanceSnapshot.objects.get(review=review, window="q1")
        original_actual = original.data["priorities"][0]["actual"]
        original_taken_at = original.taken_at

        self._verified_visit("Second", offset_days=8)
        take_snapshot(review, "q1")
        activate_window(cycle, "q1", _Principal(self.hr, self.hr_sp))

        self.assertEqual(
            PerformanceSnapshot.objects.filter(review=review, window="q1").count(), 1
        )
        original.refresh_from_db()
        self.assertEqual(original.data["priorities"][0]["actual"], original_actual)
        self.assertEqual(original.taken_at, original_taken_at)

    def test_the_computed_channel_is_not_writable_through_any_conversation_step(self):
        """ "Automatic values stay read-only", asserted at the services.

        None of the four conversation writes accepts a system score, so there
        is no argument through which a typed number could reach the computed
        channel. Checked by signature rather than by trying strings, because a
        service that silently ignored an unknown keyword would pass a
        string-based probe while a future refactor quietly wired it up.
        """
        import inspect

        from apps.hr import performance_service

        for name in (
            "submit_reflection",
            "submit_assessment",
            "calibrate",
            "acknowledge",
        ):
            with self.subTest(name):
                params = set(
                    inspect.signature(getattr(performance_service, name)).parameters
                )
                self.assertNotIn("system_score", params)
                self.assertNotIn("system_evidence", params)
                self.assertNotIn("score", params)

    def test_the_computed_score_is_rebuilt_from_the_ledger_not_carried(self):
        from apps.hr import performance_service

        review, _ = self._agreed_review()
        self._verified_visit()

        refreshed = performance_service.refresh_system_evidence(
            review.id, _Principal(self.hr, self.hr_sp)
        )
        self.assertIn(
            "targets.my_targets",
            refreshed.system_evidence["source"],
            "the review must quote the same ledger the employee's own My "
            "Targets page reads, or the two say different things about them",
        )
        self.assertIsNotNone(refreshed.system_evidence_generated_at)

    # ── Steps 2, 3, 5, 6: the conversation, and who owns each word ───────
    def test_steps_2_and_3_each_channel_has_exactly_one_author(self):
        from apps.hr import performance_service

        review, cycle = self._agreed_review()
        from apps.hr.performance_engine import activate_window

        activate_window(cycle, "q1", _Principal(self.hr, self.hr_sp))

        employee = _Principal(self.cceo, self.cceo_sp)
        manager = _Principal(self.pl, self.pl_sp)

        # The reflection is the employee's own words, and only theirs.
        for actor in (manager, _Principal(self.hr, self.hr_sp)):
            with self.subTest(f"reflection:{actor.active_role}"):
                with self.assertRaises(Forbidden):
                    performance_service.submit_reflection(
                        review.id, actor, reflection="Words in their mouth."
                    )
        performance_service.submit_reflection(
            review.id,
            employee,
            reflection="I reached every school but two; both were closed.",
        )
        review.refresh_from_db()
        self.assertEqual(review.stage, ReviewStage.MANAGER_ASSESSMENT)

        # The assessment is the manager's judgement — not the employee's, and
        # not HR's on the manager's behalf.
        with self.assertRaises(Forbidden):
            performance_service.submit_assessment(
                review.id, employee, assessment="I did well."
            )
        with self.assertRaises(Forbidden):
            performance_service.submit_assessment(
                review.id,
                _Principal(self.hr, self.hr_sp),
                assessment="Written by governance.",
            )
        performance_service.submit_assessment(
            review.id,
            manager,
            assessment="Agreed; the closures are documented.",
            rating="Meets",
        )
        review.refresh_from_db()
        self.assertEqual(review.stage, ReviewStage.CALIBRATION)
        self.assertEqual(review.manager_rating, "Meets")
        self.assertIsNone(
            review.rating,
            "the manager's judgement is not the final rating — calibration "
            "decides that, and writing it here skips the gate",
        )

    def test_steps_5_and_6_calibration_decides_and_only_the_employee_closes(self):
        from apps.hr import performance_service
        from apps.hr.performance_engine import activate_window

        review, cycle = self._agreed_review()
        activate_window(cycle, "q1", _Principal(self.hr, self.hr_sp))
        employee = _Principal(self.cceo, self.cceo_sp)
        manager = _Principal(self.pl, self.pl_sp)

        performance_service.submit_reflection(
            review.id, employee, reflection="My quarter, in my words."
        )
        performance_service.submit_assessment(
            review.id, manager, assessment="Manager's view.", rating="Meets"
        )

        # Calibration is HR's or the CD's — never the manager's, never theirs.
        with self.assertRaises(Forbidden):
            performance_service.calibrate(review.id, manager, result="Exceeds")
        with self.assertRaises(Forbidden):
            performance_service.calibrate(review.id, employee, result="Exceeds")

        performance_service.calibrate(
            review.id,
            _Principal(self.cd, self.cd_sp),
            result="Meets",
            note="Cohort consistent.",
        )
        review.refresh_from_db()
        self.assertEqual(review.stage, ReviewStage.AWAITING_ACKNOWLEDGEMENT)
        self.assertEqual(review.rating, "Meets")
        self.assertIsNotNone(review.calibrated_at)

        # Acknowledgement is the ONE act reserved to the employee.
        for actor in (
            manager,
            _Principal(self.hr, self.hr_sp),
            _Principal(self.cd, self.cd_sp),
        ):
            with self.subTest(actor.active_role):
                with self.assertRaises(Forbidden):
                    performance_service.acknowledge(review.id, actor)

        performance_service.acknowledge(review.id, employee)
        review.refresh_from_db()
        self.assertEqual(review.stage, ReviewStage.CLOSED)
        self.assertIsNotNone(review.closed_at)

    # ── The whole journey, in order, as one walk ─────────────────────────
    def test_the_whole_conversation_in_order(self):
        """All seven steps, one test, because that is what covered means.

        The focused tests above each drive one rule hard — who may open the
        window, who owns which channel, what a closed review refuses. None of
        them walks the journey, and a set of tests that each verify a step
        with the seams between them faked is exactly the coverage this
        platform cannot rely on: either half passes while the join is broken.

        So this is the join. Verified work exists before the window opens; HR
        opens it and the numbers freeze; more verified work lands mid-meeting
        and does not move them; the employee writes, the manager assesses,
        calibration decides, the employee closes; and the snapshot the
        conversation was held against still reads what it read at the start.
        """
        from apps.hr import performance_service
        from apps.hr.performance_engine import activate_window, live_progress

        review, cycle = self._agreed_review()
        employee = _Principal(self.cceo, self.cceo_sp)
        manager = _Principal(self.pl, self.pl_sp)
        hr = _Principal(self.hr, self.hr_sp)

        # Work done before the quarter's conversation.
        self._verified_visit("Delivered before the window")
        priority = review.priorities.get()
        self.assertEqual(live_progress(priority)["actual"], 1)

        # Step 1 — HR unlocks, and that act takes the snapshot.
        self.assertEqual(activate_window(cycle, "q1", hr), 1)
        snapshot = PerformanceSnapshot.objects.get(review=review, window="q1")
        frozen = snapshot.data["priorities"][0]["actual"]
        self.assertEqual(frozen, 1)

        # Step 7, tested where it bites — real work lands mid-conversation.
        self._verified_visit("Delivered during the window", offset_days=8)
        self.assertEqual(
            live_progress(priority)["actual"],
            2,
            "verified work is verified work; the live figure must move",
        )
        snapshot.refresh_from_db()
        self.assertEqual(
            snapshot.data["priorities"][0]["actual"],
            frozen,
            "and the figure the meeting is being held against must not",
        )

        # Step 2 — the employee's own words.
        performance_service.submit_reflection(
            review.id,
            employee,
            reflection="Two schools reached and evidenced this quarter.",
        )
        review.refresh_from_db()
        self.assertEqual(review.stage, ReviewStage.MANAGER_ASSESSMENT)

        # Step 3 — the manager's judgement, kept separate from it.
        performance_service.submit_assessment(
            review.id,
            manager,
            assessment="Consistent with the verified record.",
            rating="Meets",
        )
        review.refresh_from_db()
        self.assertEqual(review.stage, ReviewStage.CALIBRATION)

        # Step 4 — the computed channel is rebuilt from the ledger, and none
        # of the three writes above touched it.
        self.assertIsNone(
            review.system_score,
            "no conversation step may write the computed score",
        )
        refreshed = performance_service.refresh_system_evidence(review.id, hr)
        self.assertIn("targets.my_targets", refreshed.system_evidence["source"])

        # Step 5 — HR oversight decides the rating the manager proposed.
        self.assertIsNone(review.rating)
        performance_service.calibrate(
            review.id, hr, result="Meets", note="Cohort consistent."
        )
        review.refresh_from_db()
        self.assertEqual(review.rating, "Meets")
        self.assertEqual(review.stage, ReviewStage.AWAITING_ACKNOWLEDGEMENT)

        # Step 6 — and only the employee closes it.
        performance_service.acknowledge(review.id, employee)
        review.refresh_from_db()
        self.assertEqual(review.stage, ReviewStage.CLOSED)

        # Step 7 again, at the end: the record of the conversation is the
        # record of the conversation, whatever happened afterwards.
        snapshot.refresh_from_db()
        self.assertEqual(snapshot.data["priorities"][0]["actual"], frozen)
        self.assertEqual(live_progress(priority)["actual"], 2)

        self.client.force_login(self.cceo)
        response = self.client.get("/performance-conversation")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Performance Conversation")

    def test_a_closed_conversation_cannot_be_assessed_again_in_place(self):
        """Reopening is a governed act; posting into a closed review is not."""
        from apps.hr import performance_service
        from apps.hr.performance_engine import activate_window

        review, cycle = self._agreed_review()
        activate_window(cycle, "q1", _Principal(self.hr, self.hr_sp))
        employee = _Principal(self.cceo, self.cceo_sp)
        manager = _Principal(self.pl, self.pl_sp)

        performance_service.submit_reflection(review.id, employee, reflection="Mine.")
        performance_service.submit_assessment(
            review.id, manager, assessment="Theirs.", rating="Meets"
        )
        performance_service.calibrate(
            review.id, _Principal(self.hr, self.hr_sp), result="Meets"
        )
        performance_service.acknowledge(review.id, employee)

        with self.assertRaises(BadRequest) as closed:
            performance_service.submit_assessment(
                review.id, manager, assessment="On second thoughts.", rating="Below"
            )
        self.assertIn("reopen", str(closed.exception).lower())

        review.refresh_from_db()
        self.assertEqual(review.rating, "Meets")
        self.assertEqual(review.stage, ReviewStage.CLOSED)
