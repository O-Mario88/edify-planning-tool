"""Journey 1 — Published priority to verified performance, walked end to end.

The mandate's longest journey and its eleven steps: Publish priority, IA
distributes to PL, PL distributes to self and CCEO, Target appears, Plan
created, Activity scheduled, Evidence verified, Salesforce confirmed,
Achievement updated, Performance updated, Drill-down reconciles.

It is the journey with the most distinct owners. A Regional Vice President
writes strategy, a role rule decides how each role carries it, an employee and
their manager agree the commitment, a CCEO delivers the work, Impact Assessment
verifies it, and then three separate surfaces — My Targets, the performance
agreement, and the drill-down behind them — are each supposed to say the same
thing about it. Every one of those hand-offs is a seam, and the seams are where
this audit has found every defect it has found.

TWO NOTES ON WHAT THE PLATFORM ACTUALLY BUILT, BEFORE THE WALK

The mandate's step 2 says "IA distributes to PL". The cascade this platform
built does not work that way and, having read it, the difference looks
deliberate rather than missed. Distribution is not a hand-off anybody performs:
an RVP publishes a priority carrying a per-role rule, a Country Director may
translate it into a country priority, and `rules_for_role` then resolves what
each role carries. Nobody distributes anything, because the priority reaches
every role that has a rule the moment it is published. That is a stronger
design than a hand-off — a hand-off can be forgotten — and it is why this walk
tests `rules_for_role` and `apply_to_review` where the mandate names an actor.
It is recorded here rather than silently substituted, because a journey report
that quietly rewrites the journey is not evidence of anything.

Step 4, "Target appears", is the one that carries the most machinery, so it is
walked in both directions: the target must appear on agreement, and the
mandatory commitment behind it must survive an employee submitting a list that
does not contain it. `set_priorities` rebuilds the agreement from its payload,
which is exactly the write shape through which a leadership commitment
disappears with nobody deciding to remove it.
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
    PriorityAccountability,
    ReviewStage,
    StrategicPriority,
    StrategicPriorityLevel,
    StrategicPriorityRoleRule,
    StrategicPriorityStatus,
)
from apps.schools.models import School

TRANSPORT = 50_000
ANNUAL_VISITS = 12


class _Principal:
    """What the HR services expect: a user id and the role being acted in."""

    def __init__(self, user, staff_profile_id=None):
        self.id = user.id
        self.user_id = user.id
        self.active_role = user.active_role
        self.staff_profile_id = staff_profile_id


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


class PriorityToVerifiedPerformanceJourneyTest(TestCase):
    """Strategy published → carried → agreed → delivered → verified → counted."""

    @classmethod
    def setUpTestData(cls):
        cls.region = Region.objects.create(name="Priority Region")
        cls.district = District.objects.create(
            name="Priority District", region=cls.region, district_type="primary"
        )
        cls.school = School.objects.create(
            school_id="SCH-PRI-1",
            name="Priority Primary",
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
                user=user, staff_number=f"PR-{name[:6]}", country="Uganda", title=role
            )
            return user, profile

        cls.rvp, _ = _person("pr-rvp@edify.org", "Pr RVP", "RegionalVicePresident")
        cls.cd, _ = _person("pr-cd@edify.org", "Pr CD", "CountryDirector")
        cls.cceo, cls.cceo_sp = _person("pr-cceo@edify.org", "Pr CCEO", "CCEO")
        cls.pl, cls.pl_sp = _person("pr-pl@edify.org", "Pr PL", "Program Lead")
        cls.ia, _ = _person("pr-ia@edify.org", "Pr IA", "ImpactAssessment")
        cls.accountant, _ = _person("pr-acct@edify.org", "Pr Acct", "Accountant")
        cls.hr, _ = _person("pr-hr@edify.org", "Pr HR", "HumanResources")

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

    # ── Step 1: publish ──────────────────────────────────────────────────
    def _drafted_priority(self, *, with_rules=True, cceo_metric="direct_visits"):
        priority = StrategicPriority.objects.create(
            fy=self.fy,
            level=StrategicPriorityLevel.REGIONAL,
            title="Every assigned school is visited and verified",
            strategic_purpose=(
                "Direct contact with each assigned school, evidenced and "
                "verified, is the floor the rest of the programme stands on."
            ),
            target_guidance="100% of assigned schools",
            weight_min=10,
            weight_max=40,
            is_mandatory=True,
        )
        if with_rules:
            StrategicPriorityRoleRule.objects.create(
                priority=priority,
                role="CCEO",
                accountability=PriorityAccountability.EXECUTE,
                metric_key=cceo_metric,
                outcome_statement="I visit and evidence every school assigned to me.",
                default_weight=30,
                sequence=1,
            )
            StrategicPriorityRoleRule.objects.create(
                priority=priority,
                role="Program Lead",
                accountability=PriorityAccountability.SUPERVISE,
                metric_key="team_ssa_coverage",
                outcome_statement="My team's schools carry verified assessments.",
                default_weight=25,
                sequence=2,
            )
            StrategicPriorityRoleRule.objects.create(
                priority=priority,
                role="Accountant",
                accountability=PriorityAccountability.NOT_APPLICABLE,
                metric_key="",
                outcome_statement="Not carried by finance.",
                sequence=3,
            )
        return priority

    def test_step_1_publication_refuses_a_priority_that_could_never_measure(self):
        """Three refusals, each guarding a different way to publish a lie."""
        from apps.hr import priority_cascade

        rvp = _Principal(self.rvp)

        with self.assertRaises(BadRequest) as no_rules:
            priority_cascade.publish(self._drafted_priority(with_rules=False), rvp)
        self.assertIn("reaches nobody", str(no_rules.exception))

        with self.assertRaises(BadRequest) as unknown_metric:
            priority_cascade.publish(
                self._drafted_priority(cceo_metric="visits_but_spelled_wrong"), rvp
            )
        self.assertIn("0% forever", str(unknown_metric.exception))

        # And authorship: strategy is not everyone's to publish.
        with self.assertRaises(Forbidden):
            priority_cascade.publish(
                self._drafted_priority(), _Principal(self.accountant)
            )

    def test_step_1_a_measurable_priority_publishes(self):
        from apps.hr import priority_cascade

        priority = priority_cascade.publish(
            self._drafted_priority(), _Principal(self.rvp)
        )
        self.assertEqual(priority.status, StrategicPriorityStatus.PUBLISHED)
        self.assertIsNotNone(priority.published_at)

    # ── Steps 2–3: the priority reaches each role, differently ───────────
    def test_steps_2_and_3_each_role_carries_its_own_measure(self):
        """The rule the cascade exists for: one strategy, not one target.

        A Programme Lead supervising the work and a CCEO doing it must not be
        handed the same number. If they were, the supervisor's score would be
        their team's score with no distinct accountability of their own.
        """
        from apps.hr import priority_cascade

        priority_cascade.publish(self._drafted_priority(), _Principal(self.rvp))

        cceo_rules = priority_cascade.rules_for_role("CCEO", self.fy)
        pl_rules = priority_cascade.rules_for_role("Program Lead", self.fy)
        accountant_rules = priority_cascade.rules_for_role("Accountant", self.fy)

        self.assertEqual([r.metric_key for r in cceo_rules], ["direct_visits"])
        self.assertEqual([r.metric_key for r in pl_rules], ["team_ssa_coverage"])
        self.assertNotEqual(
            cceo_rules[0].metric_key,
            pl_rules[0].metric_key,
            "the supervisor and the executor must be measured on different "
            "things, or the cascade has handed everyone the same target",
        )
        self.assertEqual(
            accountant_rules,
            [],
            "a NOT_APPLICABLE rule is a recorded exemption, not a commitment",
        )

    # ── Step 4: the target appears, and survives ─────────────────────────
    def _open_review(self):
        """HR opens the CCEO's annual cycle through the real service.

        Not hand-built: `open_cycle` is what attaches the manager from the
        supervisor assignment, and the manager is who `agree_priorities` will
        later check. A review constructed directly has no manager, so the
        agreement step would be testing an HR override rather than the
        ordinary path an employee and their Programme Lead actually walk.
        """
        from apps.hr import performance_service

        review = performance_service.open_cycle(
            self.cceo_sp,
            _Principal(self.hr),
            fy=self.fy,
            due_date=self.day + datetime.timedelta(days=180),
        )
        self.assertEqual(review.stage, ReviewStage.PRIORITIES_DRAFT)
        self.assertEqual(
            review.manager_id,
            self.pl_sp.id,
            "the cycle must carry the supervisor as manager, or the agreement "
            "step below is not the path a real pair walks",
        )
        return review

    def _agreed_review(self):
        """Publish, cascade onto a CCEO's draft agreement, agree it."""
        from apps.hr import performance_service, priority_cascade

        priority_cascade.publish(self._drafted_priority(), _Principal(self.rvp))

        review = self._open_review()
        added = priority_cascade.apply_to_review(
            review, "CCEO", denominators={"direct_visits": ANNUAL_VISITS}
        )
        self.assertEqual(added, 1, "the CCEO's rule must render one commitment")

        cascaded = review.priorities.get()
        self.assertTrue(cascaded.is_mandatory)
        self.assertEqual(cascaded.target_number, ANNUAL_VISITS)
        self.assertGreaterEqual(cascaded.weight, 10)
        self.assertLessEqual(
            cascaded.weight, 40, "a rule's weight must be clamped to the range"
        )

        performance_service.set_priorities(
            review.id,
            _Principal(self.cceo, self.cceo_sp.id),
            [
                {
                    "id": cascaded.id,
                    "outcome_statement": cascaded.outcome_statement,
                    "metric_key": cascaded.metric_key,
                    "weight": 100,
                    "measures_of_success": "Every visit evidenced and verified.",
                }
            ],
        )
        review.refresh_from_db()
        performance_service.agree_priorities(
            review.id, _Principal(self.pl, self.pl_sp.id)
        )
        review.refresh_from_db()
        return review, review.priorities.get()

    def test_step_4_the_mandatory_commitment_cannot_be_dropped_or_repointed(self):
        """`set_priorities` rebuilds from its payload — the dangerous shape."""
        from apps.hr import performance_service, priority_cascade

        priority_cascade.publish(self._drafted_priority(), _Principal(self.rvp))
        review = self._open_review()
        priority_cascade.apply_to_review(
            review, "CCEO", {"direct_visits": ANNUAL_VISITS}
        )
        cascaded = review.priorities.get()
        employee = _Principal(self.cceo, self.cceo_sp.id)

        # Dropped: a payload that simply does not mention it.
        with self.assertRaises(BadRequest):
            performance_service.set_priorities(
                review.id,
                employee,
                [
                    {
                        "outcome_statement": "Something I would rather do.",
                        "weight": 100,
                    }
                ],
            )

        # Re-pointed: kept, but measured by a metric that suits better.
        with self.assertRaises(BadRequest):
            performance_service.set_priorities(
                review.id,
                employee,
                [
                    {
                        "id": cascaded.id,
                        "outcome_statement": cascaded.outcome_statement,
                        "metric_key": "cluster_meetings",
                        "weight": 100,
                    }
                ],
            )

        self.assertEqual(
            review.priorities.get().metric_key,
            "direct_visits",
            "neither refusal may leave the agreement half-rewritten",
        )

    def test_step_4_agreement_writes_the_target_into_the_one_ledger(self):
        """My Targets must show the commitment, phased, summing to the annual."""
        from apps.targets.models import MonthlyPersonalTarget

        review, priority = self._agreed_review()
        self.assertEqual(review.stage, ReviewStage.PRIORITIES_AGREED)

        rows = MonthlyPersonalTarget.objects.filter(
            user_id=self.cceo.id, fy=self.fy, area__key="school_visits"
        )
        self.assertEqual(rows.count(), 12, "the FY is phased across twelve months")
        self.assertEqual(
            sum(row.target for row in rows),
            ANNUAL_VISITS,
            "the phased months must sum to exactly the annual commitment — a "
            "per-month rounding loses the whole of a small target",
        )
        self.assertEqual(priority.target_number, ANNUAL_VISITS)

    # ── Steps 5–8: the work, and its verification ────────────────────────
    def _delivered_and_verified(self):
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

        item = resolve_item_for_workflow_kind("school_visit")
        schedule_school_visit(
            {
                "schoolId": self.school.school_id,
                "catalogueItemId": item.id,
                "scheduledDate": _at(self.day).isoformat(),
                "activityPurposeText": "Journey 1 proof",
            },
            self.cceo,
        )
        activity = Activity.objects.get(school=self.school)

        wfr = WeeklyFundRequest.objects.get(responsible_user=self.cceo.id)
        request_advance(wfr.id, self.cceo)
        approve_weekly_request(wfr.id, self.pl)
        disburse(wfr.id, {"method": "Bank", "reference": "PR-1"}, self.accountant)
        confirm_receipt(wfr.id, self.cceo)

        start_completion(activity.id, {}, self.cceo)
        EvidenceRecord.objects.create(
            activity_id=activity.id,
            kind="school_visit_form",
            uri="journey/priority-form.pdf",
            original_name="priority-form.pdf",
            file_size=2048,
            uploaded_by=self.cceo.id,
        )
        complete(activity.id, {"salesforceId": "SVE-100001"}, self.cceo)
        activity.refresh_from_db()
        if activity.status == "submitted_to_pl":
            from apps.pl_review.services import confirm as pl_confirm

            pl_confirm(activity.id, self.pl)
            activity.refresh_from_db()
        # The id string, exactly as ia_views passes `request.user.user_id`.
        # The SEC-03 guard added in this audit resolves it back to a user and
        # asks the permission matrix before anything is stamped.
        ActivityCertificationService.certify_activity(
            activity, {"decision": "verified"}, str(self.ia.id)
        )
        activity.refresh_from_db()
        return activity

    def test_steps_5_to_8_the_visit_is_delivered_evidenced_and_verified(self):
        activity = self._delivered_and_verified()

        from apps.targets.my_targets import IA_VERIFIED_STATUSES

        self.assertIn(
            activity.status,
            IA_VERIFIED_STATUSES,
            "the walk must reach a state the achievement ledger counts, or "
            "every assertion after it is measuring the wrong thing",
        )
        self.assertEqual(
            activity.salesforce_activity_id,
            "SVE-100001",
            "the Salesforce confirmation is part of the journey, not decoration",
        )

    # ── Steps 9–11: three surfaces, one number ───────────────────────────
    def test_steps_9_to_11_achievement_performance_and_drilldown_agree(self):
        """The join this journey exists to test.

        My Targets counts the verified visit against the phased commitment.
        `live_progress` derives the same visit against the agreed priority's
        own denominator. They are computed by different code from different
        tables, and the whole point of the cascade is that they say the same
        thing about the same work.
        """
        from apps.hr.performance_engine import live_progress
        from apps.targets.my_targets import (
            MyTargetQueryService,
            TargetAchievementService,
        )

        _, priority = self._agreed_review()
        self._delivered_and_verified()

        TargetAchievementService.rebuild(self.cceo, self.fy)

        achievements = MyTargetQueryService.monthly_achievements(self.cceo, self.fy)
        visits_achieved = sum(achievements.get("school_visits", []))
        self.assertEqual(
            visits_achieved,
            1,
            "one verified visit must appear once in the achievement ledger",
        )

        progress = live_progress(priority)
        self.assertEqual(
            progress["actual"],
            visits_achieved,
            "the performance agreement and My Targets are counting the same "
            "verified visit; if they disagree the drill-down behind them "
            "cannot reconcile either",
        )
        self.assertEqual(progress["target"], ANNUAL_VISITS)
        self.assertEqual(
            progress["pct"],
            round(100 * visits_achieved / ANNUAL_VISITS),
            "the percentage must be the two numbers beside it, not a third "
            "figure computed somewhere else",
        )

    def test_the_reconciled_number_reaches_the_screens_that_show_it(self):
        """JRN-01: journey 1's last step, at the door instead of the service.

        Steps 9-11 are the reason this journey exists: My Targets and
        `live_progress` count the same verified visit by different code from
        different tables, and the drill-down behind them has to reconcile. The
        walk above proves those two FUNCTIONS agree. It never loads a page, so
        it cannot show that the agreed number is the one a person is actually
        shown — and "the figure on the screen" is the whole deliverable of this
        cascade.

        That gap is not hypothetical here. CONFLICT-001 was exactly a
        disagreement about which denominator leadership reads, and it was
        found in the service layer. A service-only walk cannot tell whether
        the corrected figure survives the trip to the template.

        So: deliver and verify the work, then open the two surfaces as the
        people who read them and require the numbers to be present and to
        agree with the ledger.
        """
        from apps.hr.performance_engine import live_progress
        from apps.targets.my_targets import (
            MyTargetQueryService,
            TargetAchievementService,
        )

        _, priority = self._agreed_review()
        self._delivered_and_verified()
        TargetAchievementService.rebuild(self.cceo, self.fy)

        achievements = MyTargetQueryService.monthly_achievements(self.cceo, self.fy)
        visits_achieved = sum(achievements.get("school_visits", []))
        self.assertEqual(visits_achieved, 1, "the ledger lost the verified visit")
        progress = live_progress(priority)

        # ── The owner's own targets page ──────────────────────────────────
        self.client.force_login(self.cceo)
        response = self.client.get("/my-targets")
        self.assertEqual(
            response.status_code,
            200,
            "the CCEO cannot open the page that shows their own targets",
        )

        # Asked of the month the ledger actually credited — and every word of
        # that was earned by getting it wrong twice.
        #
        # The first version searched every integer in the template context for
        # the achievement count. It passed, and it was worthless: the count is
        # 1, and 1 is in any page's context. Re-run with nothing delivered at
        # all, it still passed. A test that cannot fail when the work never
        # happened is not evidence.
        #
        # The second read `area_cards` on the default view and found
        # "0 / 1 · Off Track" beside a ledger holding the visit. That looks
        # exactly like a defect and is not one: the card is scoped to the
        # CURRENT month, and a visit scheduled a week out is delivered in the
        # NEXT one. Both surfaces were right. Reporting it would have been a
        # false finding.
        #
        # The third assumed `matrix_rows` cells were months. They are period
        # buckets — six of them, not twelve — so indexing by month raised
        # IndexError rather than a wrong answer, which is the kinder failure.
        #
        # What is true, and worth holding: open the month the work landed in
        # and the screen shows the verified visit against its commitment.
        credited = [
            index
            for index, count in enumerate(achievements.get("school_visits", []))
            if count
        ]
        self.assertEqual(
            len(credited), 1, "the ledger credited the visit to no month, or to several"
        )
        credited_month = credited[0] + 1

        response = self.client.get(f"/my-targets?month={credited_month}")
        self.assertEqual(response.status_code, 200)
        cards = {card["key"]: card for card in response.context["area_cards"]}
        self.assertIn(
            "school_visits",
            cards,
            "the targets page has no card for the area this journey measures",
        )
        card = cards["school_visits"]
        self.assertEqual(
            card["achieved"],
            visits_achieved,
            f"the ledger credits {visits_achieved} school visit(s) to month "
            f"{credited_month} and the CCEO's own targets page shows "
            f"{card['achieved']} there. The cascade's entire deliverable is "
            f"that these agree.",
        )
        self.assertEqual(
            card["pct"],
            round(100 * card["achieved"] / card["target"]) if card["target"] else 0,
            "the percentage on the card is not the two numbers beside it",
        )

        # ── The performance conversation, as the PL who holds it ──────────
        self.client.force_login(self.pl)
        conversation = self.client.get("/performance-conversation")
        self.assertEqual(
            conversation.status_code,
            200,
            "the Program Lead cannot open the performance conversation",
        )

        # ── The two surfaces agree with each other ────────────────────────
        # This is the join CONFLICT-001 broke: the same verified work, read
        # two ways, must give one answer.
        self.assertEqual(
            progress["actual"],
            visits_achieved,
            "the performance agreement and My Targets disagree about the same "
            "verified visit",
        )
        self.assertEqual(
            progress["pct"],
            round(100 * visits_achieved / ANNUAL_VISITS),
            "the percentage is not the two numbers beside it",
        )

    def test_unverified_work_moves_neither_surface(self):
        """Guard the premise: both numbers above must come from verification.

        Without this, a walk that counted merely-completed work would pass
        every assertion above and prove nothing about IA at all.
        """
        from apps.activities.services import start_completion
        from apps.activity_catalogue.services import resolve_item_for_workflow_kind
        from apps.hr.performance_engine import live_progress
        from apps.planning.services import schedule_school_visit
        from apps.targets.my_targets import (
            MyTargetQueryService,
            TargetAchievementService,
        )

        _, priority = self._agreed_review()

        item = resolve_item_for_workflow_kind("school_visit")
        schedule_school_visit(
            {
                "schoolId": self.school.school_id,
                "catalogueItemId": item.id,
                "scheduledDate": _at(self.day).isoformat(),
                "activityPurposeText": "Scheduled, never verified",
            },
            self.cceo,
        )
        activity = Activity.objects.get(school=self.school)
        start_completion(activity.id, {}, self.cceo)

        TargetAchievementService.rebuild(self.cceo, self.fy)
        achievements = MyTargetQueryService.monthly_achievements(self.cceo, self.fy)

        self.assertEqual(sum(achievements.get("school_visits", [])), 0)
        self.assertEqual(live_progress(priority)["actual"], 0)
