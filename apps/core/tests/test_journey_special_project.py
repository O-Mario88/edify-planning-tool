"""Journey 6 — the Special Project, walked end to end.

Ten steps: IA maps SSA intervention, Assigns Project Coordinator, Staff adds
eligible school, Baseline captured, Activity planned, Costed, Delivered, IA
verified, Follow-up SSA, Impact calculated.

The last unwritten journey of the mandate's twenty-two, and walking it found
PROJ-01 — `ssa_impact.refresh_follow_up`, the only code that can move a project
school out of "not yet measurable", had no caller anywhere in production. Step
10 was therefore unreachable: every project reported "not measured yet" for
ever, however much verified work was done. That is fixed (see
apps/projects/test_impact_measurement_is_reachable.py); this walk is what
found it and what now holds the whole chain together.

WHAT THIS JOURNEY IS ACTUALLY ABOUT

Every other journey moves work or money. This one moves a claim: at the end of
it the platform says a project improved something. So the interesting rules are
all about what the platform refuses to claim, and they are unusually good:

  * a school is added to a project because its own confirmed assessment is
    genuinely weak in one of the project's declared target interventions —
    "never fabricate need"
  * the baseline is snapshotted at assignment, so the score the project is
    later judged against is the one it started from, not whatever the latest
    assessment happens to say
  * measurement starts from a VERIFIED delivery, not a scheduled one, because
    "a plan is not an intervention, and measuring from a date nothing happened
    on would open the follow-up window early"
  * a rate is withheld entirely below a minimum cohort rather than shown with
    a caveat nobody reads

That last one shapes the end of this walk. One school is a real, measured,
improved school AND too small a cohort to state a project-level rate, and both
of those are correct at once. The walk asserts both, because a test that
demanded a percentage here would be asking the platform to overclaim.
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
from apps.core.exceptions import BadRequest
from apps.core.fy import get_operational_fy
from apps.geography.models import District, Region
from apps.projects import ssa_impact
from apps.projects.models import Project, ProjectSchoolAssignment
from apps.schools.models import School
from apps.ssa.models import SsaRecord, SsaScore

TRANSPORT = 50_000
TARGET = "christlike_behaviour"
WEAK = 3.0
STRONG = 8.5


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


class SpecialProjectJourneyTest(TestCase):
    """Mapped intervention → project → school → delivery → verified → measured."""

    @classmethod
    def setUpTestData(cls):
        cls.region = Region.objects.create(name="Special Project Region")
        cls.district = District.objects.create(
            name="Special Project District",
            region=cls.region,
            district_type="primary",
        )
        cls.school = School.objects.create(
            school_id="SCH-SPP-1",
            name="Special Project Primary",
            region=cls.region,
            district=cls.district,
            school_type="client",
            enrollment=300,
        )
        # A school strong in the target intervention. Step 3's refusal is only
        # meaningful if something in the fixture genuinely does not need help.
        cls.strong_school = School.objects.create(
            school_id="SCH-SPP-2",
            name="Already Strong Primary",
            region=cls.region,
            district=cls.district,
            school_type="client",
            enrollment=300,
        )

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
                user=user, staff_number=f"SP-{name[:6]}", country="Uganda", title=role
            )
            return user, profile

        cls.ia, cls.ia_sp = _person("spp-ia@edify.org", "Spp IA", "ImpactAssessment")
        cls.cd, cls.cd_sp = _person("spp-cd@edify.org", "Spp CD", "CountryDirector")
        cls.pc, cls.pc_sp = _person("spp-pc@edify.org", "Spp PC", "ProjectCoordinator")
        cls.cceo, cls.cceo_sp = _person("spp-cceo@edify.org", "Spp CCEO", "CCEO")
        cls.pl, cls.pl_sp = _person("spp-pl@edify.org", "Spp PL", "Program Lead")
        cls.accountant, _ = _person("spp-acct@edify.org", "Spp Acct", "Accountant")

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

    def setUp(self):
        self.today = timezone.localdate()

    # ── Assessments ──────────────────────────────────────────────────────
    def _ssa(self, school, on, score, *, status="confirmed"):
        record = SsaRecord.objects.create(
            school=school,
            fy=self.fy,
            quarter="Q1",
            average_score=score,
            verification_status=status,
            date_of_ssa=on,
            uploaded_by=self.ia.id,
            verified_by_user_id=self.ia.id,
            verified_at=timezone.now(),
        )
        SsaScore.objects.create(ssa_record=record, intervention=TARGET, score=score)
        self._drain()
        return record

    def _drain(self):
        from apps.outbox.services import drain

        return drain()

    # ── Steps 1–2: the project, and who runs it ──────────────────────────
    def _active_project(self, name="Christlike Behaviour Uplift"):
        from apps.activity_catalogue.services import resolve_item_for_workflow_kind
        from apps.projects import services

        item = resolve_item_for_workflow_kind("school_visit")
        project_data = services.create_project(
            {
                "name": name,
                "category": "intervention_specific",
                "targetInterventions": [TARGET],
                "catalogueItemIds": [item.id],
                "managerStaffId": self.pc_sp.id,
                "schoolFocus": "all",
                "measurementStartFy": self.fy,
            },
            self.ia,
        )
        project = Project.objects.get(id=project_data["id"])
        # Projects are created `proposed`; the RVP's ratification is what lets
        # them accept work at all. Without it every assignment path below
        # refuses, which is the point of assert_accepts_new_work.
        services.apply_decision(project, "continue", self.cd, reason="Ratified")
        project.refresh_from_db()
        return project

    def test_step_1_a_project_must_declare_what_it_intends_to_move(self):
        """No target intervention means nothing can be measured, so it is refused."""
        from apps.activity_catalogue.services import resolve_item_for_workflow_kind
        from apps.projects import services

        item = resolve_item_for_workflow_kind("school_visit")
        with self.assertRaises(BadRequest) as no_target:
            services.create_project(
                {
                    "name": "Vague Project",
                    "category": "intervention_specific",
                    "targetInterventions": [],
                    "catalogueItemIds": [item.id],
                },
                self.ia,
            )
        self.assertIn("impact measurement", str(no_target.exception))

        with self.assertRaises(BadRequest):
            services.create_project(
                {
                    "name": "Misspelt Project",
                    "category": "intervention_specific",
                    "targetInterventions": ["not_an_ssa_intervention"],
                    "catalogueItemIds": [item.id],
                },
                self.ia,
            )

    def test_step_2_the_project_carries_its_coordinator(self):
        project = self._active_project()
        self.assertEqual(project.manager_staff_id, self.pc_sp.id)
        self.assertTrue(project.accepts_new_work)

    # ── Steps 3–4: eligibility, and the baseline it fixes ────────────────
    def test_step_3_a_school_is_added_on_evidence_of_need_not_on_a_hunch(self):
        from apps.projects import services

        project = self._active_project()
        self._ssa(self.school, timezone.now() - datetime.timedelta(days=30), WEAK)
        self._ssa(
            self.strong_school, timezone.now() - datetime.timedelta(days=30), STRONG
        )

        services.assign_school(project.id, {"schoolId": self.school.school_id}, self.cd)
        assignment = ProjectSchoolAssignment.objects.get(
            project=project, school=self.school
        )
        self.assertEqual(assignment.matched_intervention, TARGET)

        # A school that is already strong is off-recommendation, and the
        # platform will not invent a need for it.
        with self.assertRaises(BadRequest) as no_need:
            services.assign_school(
                project.id, {"schoolId": self.strong_school.school_id}, self.cd
            )
        self.assertIn("reason", str(no_need.exception).lower())

    def test_step_4_the_baseline_is_the_score_at_entry(self):
        """Not the latest reading — the one the project starts from."""
        from apps.projects import services

        project = self._active_project()
        self._ssa(self.school, timezone.now() - datetime.timedelta(days=400), WEAK)
        services.assign_school(project.id, {"schoolId": self.school.school_id}, self.cd)

        assignment = ProjectSchoolAssignment.objects.get(
            project=project, school=self.school
        )
        self.assertEqual(assignment.baseline_score, WEAK)
        self.assertIsNotNone(assignment.baseline_captured_at)
        self.assertEqual(
            assignment.impact_classification,
            ssa_impact.Impact.NOT_YET_MEASURABLE,
            "a school with a baseline and no delivery is awaiting measurement, "
            "which is a different statement from having no evidence",
        )

    # ── Steps 5–8: the work, costed, delivered, verified ─────────────────
    def _delivered_and_verified(self, project):
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
                "activityPurposeText": "Journey 6 proof",
                "projectId": project.id,
            },
            self.cceo,
        )
        activity = Activity.objects.get(school=self.school, project_id=project.id)

        # Step 6 — costed. The schedule raises the advance; the money path is
        # walked because "costed" is a step of this journey, not a detail.
        wfr = WeeklyFundRequest.objects.get(responsible_user=self.cceo.id)
        request_advance(wfr.id, self.cceo)
        approve_weekly_request(wfr.id, self.pl)
        disburse(wfr.id, {"method": "Bank", "reference": "SPP-1"}, self.accountant)
        confirm_receipt(wfr.id, self.cceo)
        self.assertTrue(
            activity.schedule_cost_lines.exists(),
            "a project activity must carry the cost lines it was funded on",
        )

        start_completion(activity.id, {}, self.cceo)
        EvidenceRecord.objects.create(
            activity_id=activity.id,
            kind="school_visit_form",
            uri="journey/special-project.pdf",
            original_name="special-project.pdf",
            file_size=2048,
            uploaded_by=self.cceo.id,
        )
        complete(activity.id, {"salesforceId": "SVE-600001"}, self.cceo)
        activity.refresh_from_db()
        if activity.status == "submitted_to_pl":
            from apps.pl_review.services import confirm as pl_confirm

            pl_confirm(activity.id, self.pl)
            activity.refresh_from_db()
        ActivityCertificationService.certify_activity(
            activity, {"decision": "verified"}, str(self.ia.id)
        )
        activity.refresh_from_db()
        self._drain()
        return activity

    # ── The whole journey, in order, as one walk ─────────────────────────
    def test_the_whole_special_project_in_order(self):
        """All ten steps, one test, because that is what covered means."""
        from apps.projects import services

        # 1–2. The project declares what it exists to move, and who runs it.
        project = self._active_project()

        # 3–4. A school is added on its own evidence of need, and the score it
        # starts from is fixed at that moment.
        self._ssa(self.school, timezone.now() - datetime.timedelta(days=400), WEAK)
        services.assign_school(project.id, {"schoolId": self.school.school_id}, self.cd)
        assignment = ProjectSchoolAssignment.objects.get(
            project=project, school=self.school
        )
        self.assertEqual(assignment.baseline_score, WEAK)

        # 5–8. Planned, costed, delivered, IA-verified.
        activity = self._delivered_and_verified(project)
        from apps.targets.my_targets import IA_VERIFIED_STATUSES

        self.assertIn(activity.status, IA_VERIFIED_STATUSES)

        # Verified delivery is what opens the measurement window — PROJ-01.
        assignment.refresh_from_db()
        self.assertIsNotNone(
            assignment.follow_up_due_on,
            "a verified delivery must fix the date the follow-up is due from",
        )

        # 9. The follow-up assessment, confirmed and after the work.
        #
        # Dated after the delivery, which is itself in the future: the
        # scheduler will not accept a visit in the past, so a walk that has to
        # deliver AND then re-assess inside one test necessarily runs on
        # future dates. What matters is the ordering the platform enforces —
        # `follow_up_for` takes the first confirmed reading at or after the
        # verified delivery, and an assessment before it is not evidence of
        # it. That refusal is driven by
        # test_an_unverified_delivery_measures_nothing below and by
        # test_a_follow_up_before_delivery_does_not_judge_the_delivery in
        # apps/projects/test_impact_measurement_is_reachable.py.
        self._ssa(self.school, _at(self.day + datetime.timedelta(days=120)), STRONG)

        # 10. And the project can state its position.
        assignment.refresh_from_db()
        self.assertEqual(assignment.follow_up_score, STRONG)
        self.assertIn(assignment.impact_classification, ssa_impact.MEASURED)

        impact = ssa_impact.project_impact(project, intervention=TARGET)
        self.assertEqual(impact["pipeline"]["measured"], 1)
        self.assertEqual(impact["improved"], 1)
        self.assertEqual(impact["average_change"], round(STRONG - WEAK, 2))

        # And still refuses to turn one school into a rate. Both of these are
        # correct at the same time, which is the point.
        self.assertEqual(impact["cohort_size"], 1)
        self.assertFalse(impact["has_enough_evidence"])
        self.assertIsNone(
            impact["improvement_rate"],
            "one measured school is a measured school and not a percentage",
        )
        self.assertIn("not enough", impact["limitation"].lower())

    def test_an_unverified_delivery_measures_nothing(self):
        """Guard the premise: a plan is not an intervention."""
        from apps.activity_catalogue.services import resolve_item_for_workflow_kind
        from apps.planning.services import schedule_school_visit
        from apps.projects import services

        project = self._active_project()
        self._ssa(self.school, timezone.now() - datetime.timedelta(days=400), WEAK)
        services.assign_school(project.id, {"schoolId": self.school.school_id}, self.cd)

        item = resolve_item_for_workflow_kind("school_visit")
        schedule_school_visit(
            {
                "schoolId": self.school.school_id,
                "catalogueItemId": item.id,
                "scheduledDate": _at(self.day).isoformat(),
                "activityPurposeText": "Scheduled, never delivered",
                "projectId": project.id,
            },
            self.cceo,
        )
        self._drain()
        self._ssa(self.school, timezone.now(), STRONG)

        assignment = ProjectSchoolAssignment.objects.get(
            project=project, school=self.school
        )
        self.assertIsNone(
            assignment.follow_up_score,
            "a scheduled visit is not a delivery; measuring from it would "
            "credit the project with an improvement it did not cause",
        )
        impact = ssa_impact.project_impact(project, intervention=TARGET)
        self.assertEqual(impact["pipeline"]["measured"], 0)
        self.assertEqual(impact["pipeline"]["awaiting_follow_up"], 1)
