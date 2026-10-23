"""The ledger: every Team Performance figure read from the records behind it.

Owner, 2026-10-20: the FY27 Weekly Report's figures "should sync with the
database data" — the work staff planned and completed, and what the school
profile and the Salesforce uploads record (docs/team-performance-report.md).
Work is credited to the school's account owner, whoever delivered it.
"""

from __future__ import annotations

from datetime import date, datetime, timezone as dt_tz

from django.test import TestCase

from apps.accounts.models import StaffProfile, User
from apps.activities.models import Activity, ClusterActivityAttendance
from apps.activity_catalogue.models import ActivityCatalogueItem
from apps.clusters.models import Cluster
from apps.core_schools.models import CoreActivitySlot, CorePlan, CoreSchoolOnboarding
from apps.geography.models import District, Region
from apps.impact.models import DiscipleshipIndicatorRecord, LearningAssessmentResult
from apps.schools.models import School, SchoolEnrollmentHistory
from apps.ssa.models import SsaRecord
from apps.targets.models import MostSignificantChangeStory
from apps.team_performance import measures
from apps.team_performance.ledger import Ledger

FY = "2027"


def month(m: int) -> tuple[date, date]:
    """[start, end) of a calendar month inside FY 2027."""
    year = 2026 if m >= 10 else 2027
    end = date(year + 1, 1, 1) if m == 12 else date(year, m + 1, 1)
    return date(year, m, 1), end


YEAR = (date(2026, 10, 1), date(2027, 10, 1))


def make_officer(email: str, role: str = "CCEO") -> User:
    user = User.objects.create(
        email=email,
        name=email.split("@")[0].title(),
        roles=[role],
        active_role=role,
        is_active=True,
        status="active",
    )
    StaffProfile.objects.create(user=user)
    return user


class LedgerFixture(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.region = Region.objects.create(name="Northern Region")
        cls.district = District.objects.create(name="Gulu", region=cls.region)
        cls.cluster = Cluster.objects.create(
            name="Gulu Cluster", region=cls.region, district=cls.district
        )
        cls.james = make_officer("james@tp.test")
        cls.mary = make_officer("mary@tp.test")
        cls.core = cls.school("TP-CORE", cls.james, "core")
        cls.client_school = cls.school("TP-CLIENT", cls.james, "client")
        cls.other = cls.school("TP-OTHER", cls.mary, "client")

    @classmethod
    def school(cls, code, owner, kind, **extra) -> School:
        return School.objects.create(
            school_id=code,
            name=f"School {code}",
            school_type=kind,
            region=cls.region,
            district=cls.district,
            cluster_id=cls.cluster.id,
            account_owner_id=owner.staff_profile.id,
            **extra,
        )

    def work(self, kind, school=None, *, day, status="ia_verified", **extra):
        return Activity.objects.create(
            activity_type=kind,
            school=school,
            cluster=self.cluster if school is None else None,
            status=status,
            fy=FY,
            planned_date=day,
            **extra,
        )

    def ledger(self) -> Ledger:
        return Ledger.load(FY)

    def staff(self, user) -> set[str]:
        return {user.staff_profile.id}


class VisitsTest(LedgerFixture):
    def test_a_completed_staff_visit_counts_for_the_schools_owner_in_its_month(self):
        self.work("school_visit", self.client_school, day=date(2026, 11, 3))

        ledger = self.ledger()

        nov, dec = month(11), month(12)
        self.assertEqual(
            ledger.count("client_visit_staff", self.staff(self.james), *nov), 1
        )
        self.assertEqual(
            ledger.count("client_visit_staff", self.staff(self.james), *dec), 0
        )
        self.assertEqual(
            ledger.count("client_visit_staff", self.staff(self.mary), *nov), 0
        )
        self.assertEqual(
            ledger.count("client_visit_partner", self.staff(self.james), *nov), 0
        )

    def test_planned_work_is_not_achievement(self):
        self.work(
            "school_visit",
            self.client_school,
            day=date(2026, 11, 3),
            status="scheduled",
        )

        self.assertEqual(self.ledger().count("client_visit_total", None, *YEAR), 0)

    def test_the_day_it_was_done_places_it_not_the_day_it_was_planned(self):
        self.work(
            "school_visit",
            self.client_school,
            day=date(2026, 11, 20),
            actual_delivery_date=date(2026, 12, 2),
        )

        ledger = self.ledger()

        self.assertEqual(ledger.count("client_visit_total", None, *month(11)), 0)
        self.assertEqual(ledger.count("client_visit_total", None, *month(12)), 1)

    def test_a_partner_visit_is_reported_apart_and_a_school_counts_once(self):
        self.work("school_visit", self.client_school, day=date(2026, 11, 3))
        self.work(
            "school_visit",
            self.client_school,
            day=date(2026, 11, 9),
            delivery_type="partner",
        )

        ledger = self.ledger()

        self.assertEqual(ledger.count("client_visit_staff", None, *YEAR), 1)
        self.assertEqual(ledger.count("client_visit_partner", None, *YEAR), 1)
        self.assertEqual(ledger.count("client_visit_total", None, *YEAR), 1)

    def test_completed_work_counts_once_submitted_and_drops_out_when_returned(self):
        """Owner, 2026-10-20: achieved "when the officer completes it"."""
        self.work(
            "school_visit",
            self.client_school,
            day=date(2026, 11, 3),
            status="submitted_to_pl",
        )
        self.work(
            "school_visit", self.other, day=date(2026, 11, 3), status="returned_by_pl"
        )

        ledger = self.ledger()

        self.assertEqual(ledger.count("client_visit_total", None, *YEAR), 1)
        self.assertEqual(
            ledger.count("client_visit_total", self.staff(self.mary), *YEAR), 0
        )

    def test_the_plan_counts_scheduled_and_done_work_but_not_cancelled(self):
        self.work(
            "school_visit",
            self.client_school,
            day=date(2026, 11, 3),
            status="scheduled",
        )
        self.work(
            "school_visit", self.other, day=date(2026, 11, 4), status="ia_verified"
        )
        self.work("school_visit", self.core, day=date(2026, 11, 5), status="cancelled")

        ledger = self.ledger()

        self.assertEqual(ledger.planned("client_visit_total", None, *YEAR), 2)
        self.assertEqual(ledger.count("client_visit_total", None, *YEAR), 1)
        self.assertEqual(ledger.planned("client_visit_total", None, *month(12)), 0)
        # A row with no plan behind it has no planned figure.
        self.assertIsNone(ledger.planned("ssa_client", None, *YEAR))

    def test_a_core_school_visit_is_not_a_client_visit(self):
        self.work("school_visit", self.core, day=date(2026, 11, 3))

        self.assertEqual(self.ledger().count("client_visit_total", None, *YEAR), 0)


class TrainingsTest(LedgerFixture):
    def test_a_cluster_training_credits_each_attending_school_by_its_topic(self):
        course = ActivityCatalogueItem.objects.get(
            stable_code="LITERACY_NUMERACY_PROJECT"
        )
        session = self.work(
            "cluster_training", day=date(2026, 11, 12), catalogue_item=course
        )
        for school, attended in ((self.client_school, True), (self.other, False)):
            ClusterActivityAttendance.objects.create(
                activity=session, school=school, invited=True, attended=attended
            )

        ledger = self.ledger()

        self.assertEqual(
            ledger.count("literacy_numeracy", self.staff(self.james), *YEAR), 1
        )
        self.assertEqual(
            ledger.count("literacy_numeracy", self.staff(self.mary), *YEAR), 0
        )
        self.assertEqual(ledger.count("client_trained", None, *YEAR), 1)

    def test_a_cluster_meeting_held_as_a_training_counts_as_one(self):
        """Owner, 2026-10-06: a Training meeting "delivers a course from the
        Training Catalogue"; an Only Meeting does not."""
        course = ActivityCatalogueItem.objects.get(
            stable_code="LITERACY_NUMERACY_PROJECT"
        )
        training = self.work(
            "cluster_meeting",
            day=date(2026, 11, 12),
            meeting_kind="training",
            training_course=course,
        )
        meeting = self.work(
            "cluster_meeting", day=date(2026, 11, 13), meeting_kind="only_meeting"
        )
        for session in (training, meeting):
            ClusterActivityAttendance.objects.create(
                activity=session, school=self.client_school, invited=True, attended=True
            )

        ledger = self.ledger()

        self.assertEqual(ledger.count("literacy_numeracy", None, *YEAR), 1)
        self.assertEqual(ledger.count("client_trained", None, *YEAR), 1)
        # Both were cluster meetings held.
        self.assertEqual(ledger.count("cluster_meetings", None, *YEAR), 2)

    def test_a_cluster_session_is_planned_for_every_school_invited(self):
        course = ActivityCatalogueItem.objects.get(
            stable_code="LITERACY_NUMERACY_PROJECT"
        )
        session = self.work(
            "cluster_training",
            day=date(2026, 11, 12),
            status="scheduled",
            catalogue_item=course,
        )
        for school in (self.client_school, self.other):
            ClusterActivityAttendance.objects.create(
                activity=session, school=school, invited=True
            )

        ledger = self.ledger()

        self.assertEqual(ledger.planned("literacy_numeracy", None, *month(11)), 2)
        self.assertEqual(
            ledger.planned("literacy_numeracy", self.staff(self.mary), *YEAR), 1
        )
        self.assertEqual(ledger.count("literacy_numeracy", None, *YEAR), 0)

    def test_leaders_trained_count_leaders_and_teachers_trained_count_teachers(self):
        """SIP_LEADERS is "Leaders trained", ECD_TEACHERS "Teachers trained":
        each counts its own people, not the whole room."""
        for code in ("SCHOOL_LEADERSHIP", "EARLY_CHILDHOOD_EDUCATION_PROJECT"):
            self.work(
                "in_school_training",
                self.client_school,
                day=date(2026, 11, 12),
                catalogue_item=ActivityCatalogueItem.objects.get(stable_code=code),
                teachers_attended=7,
                leaders_attended=3,
            )
        self.work(
            "in_school_training",
            self.core,
            day=date(2026, 11, 12),
            catalogue_item=ActivityCatalogueItem.objects.get(
                stable_code="GOVERNMENT_STATUTORY_REQUIREMENTS"
            ),
            teachers_attended=4,
            leaders_attended=2,
        )

        ledger = self.ledger()

        self.assertEqual(ledger.count("sip_leaders", None, *YEAR), 3)
        self.assertEqual(ledger.count("ece_teachers", None, *YEAR), 7)
        self.assertEqual(ledger.count("government_core_participants", None, *YEAR), 6)

    def test_the_course_taught_in_school_names_the_topic(self):
        course = ActivityCatalogueItem.objects.get(stable_code="EDTECH_INTEGRATION")
        self.work(
            "in_school_training",
            self.core,
            day=date(2026, 11, 12),
            training_course=course,
        )

        ledger = self.ledger()

        self.assertEqual(ledger.count("edtech_integration_core", None, *YEAR), 1)
        self.assertEqual(ledger.count("edtech_integration_client", None, *YEAR), 0)

    def test_online_sessions_count_sessions_and_schools_apart(self):
        self.work(
            "training",
            self.client_school,
            day=date(2026, 11, 12),
            delivery_method_snapshot="online",
        )
        self.work(
            "training",
            self.client_school,
            day=date(2026, 11, 19),
            delivery_method_snapshot="online",
        )

        ledger = self.ledger()

        self.assertEqual(ledger.count("online_sessions", None, *YEAR), 2)
        self.assertEqual(ledger.count("online_schools", None, *YEAR), 1)


class CorePackageTest(LedgerFixture):
    def slot(self, plan, kind, n, day):
        visit = self.work(
            "school_visit" if kind == "visit" else "in_school_training",
            self.core,
            day=day,
        )
        return CoreActivitySlot.objects.create(
            id=f"cslot-{plan.school_id}-{kind[0]}{n}-{FY}",
            core_plan=plan,
            school_id=plan.school_id,
            intervention="leadership",
            activity_type=kind,
            sequence_number=n,
            status="ia_verified",
            activity_id=visit.id,
        )

    def test_a_core_school_counts_when_its_nth_package_visit_is_done(self):
        plan = CorePlan.objects.create(
            id=f"cplan-TP-CORE-{FY}", school_id="TP-CORE", fy=FY
        )
        self.slot(plan, "visit", 1, date(2026, 10, 20))
        self.slot(plan, "visit", 2, date(2026, 12, 4))

        ledger = self.ledger()

        self.assertEqual(ledger.count("core_visit_1", None, *YEAR), 1)
        self.assertEqual(ledger.count("core_visit_2", None, *YEAR), 1)
        self.assertEqual(ledger.count("core_visit_3", None, *YEAR), 0)
        # The month the second visit came in.
        self.assertEqual(ledger.count("core_visit_2", None, *month(12)), 1)
        self.assertEqual(ledger.count("core_visit_2", None, *month(10)), 0)

    def test_a_package_visit_dated_before_the_year_is_still_the_first(self):
        plan = CorePlan.objects.create(
            id=f"cplan-TP-CORE-{FY}", school_id="TP-CORE", fy=FY
        )
        self.slot(plan, "visit", 1, date(2026, 9, 28))  # just before FY 2027
        self.slot(plan, "visit", 2, date(2026, 12, 4))

        ledger = self.ledger()

        self.assertEqual(ledger.count("core_visit_1", None, *YEAR), 1)
        self.assertEqual(ledger.count("core_visit_2", None, *YEAR), 1)
        self.assertEqual(ledger.count("core_visit_1", None, *month(10)), 1)

    def test_a_package_visit_is_achieved_by_its_work_not_the_slot(self):
        """A visit sent back to the officer leaves achievement and stays in
        the plan; a booked one is planned only."""
        plan = CorePlan.objects.create(
            id=f"cplan-TP-CORE-{FY}", school_id="TP-CORE", fy=FY
        )
        first = self.slot(plan, "visit", 1, date(2026, 10, 20))
        Activity.objects.filter(id=first.activity_id).update(status="returned_by_pl")
        second = self.slot(plan, "visit", 2, date(2026, 12, 4))
        Activity.objects.filter(id=second.activity_id).update(status="scheduled")

        ledger = self.ledger()

        self.assertEqual(ledger.count("core_visit_1", None, *YEAR), 0)
        self.assertEqual(ledger.planned("core_visit_1", None, *month(10)), 1)
        self.assertEqual(ledger.planned("core_visit_2", None, *month(12)), 1)
        self.assertIsNone(ledger.planned("msc", None, *YEAR))

    def test_a_new_core_school_is_one_given_its_core_school_orientation(self):
        """Owner, 2026-10-20: "any new core schools with core school
        orientation training should be counted new core school and should
        count towards new core school target"."""
        orientation = ActivityCatalogueItem.objects.get(
            stable_code="CORE_SCHOOL_ORIENTATION"
        )
        self.work(
            "in_school_training",
            self.core,
            day=date(2026, 11, 2),
            catalogue_item=orientation,
        )
        # Booked, not yet held: planned only.
        self.work(
            "in_school_training",
            self.core,
            day=date(2027, 1, 12),
            status="scheduled",
            catalogue_item=orientation,
        )
        # A client school given the orientation is not a Core school yet.
        self.work(
            "in_school_training",
            self.other,
            day=date(2026, 11, 2),
            catalogue_item=orientation,
        )

        ledger = self.ledger()

        self.assertEqual(
            ledger.count("core_recruitment", self.staff(self.james), *YEAR), 1
        )
        self.assertEqual(ledger.count("core_recruitment", None, *YEAR), 1)
        self.assertEqual(ledger.count("core_recruitment", None, *month(11)), 1)
        self.assertEqual(ledger.count("core_recruitment", None, *month(10)), 0)
        self.assertEqual(ledger.planned("core_recruitment", None, *month(1)), 1)
        target = measures.get("core_recruitment")
        self.assertEqual(target.milestone, "NEW_CORE_SCHOOLS")

    def test_an_onboarding_alone_is_a_baseline_not_a_recruitment(self):
        plan = CorePlan.objects.create(
            id=f"cplan-TP-CORE-{FY}", school_id="TP-CORE", fy=FY
        )
        CoreSchoolOnboarding.objects.create(
            school_id="TP-CORE",
            core_plan=plan,
            fy=FY,
            previous_school_type="client",
            baseline_ssa_record_id="ssa-x",
            baseline_average_score=5.0,
            onboarded_by_id="u",
            onboarded_by_name="U",
            onboarded_at=datetime(2026, 11, 2, tzinfo=dt_tz.utc),
        )

        ledger = self.ledger()

        self.assertEqual(ledger.count("core_recruitment", None, *YEAR), 0)
        self.assertIn(str(self.core.pk), ledger.recruits)

    def test_a_core_profiles_start_year_is_not_a_recruitment(self):
        # Profiles are rewritten at rollover: every continuing Core school
        # carries this year's start, so only an onboarding is a recruit.
        from apps.core_schools.models import CoreSchoolProfile

        plan = CorePlan.objects.create(
            id=f"cplan-TP-CORE-{FY}", school_id="TP-CORE", fy=FY
        )
        CoreSchoolProfile.objects.create(
            id="cprof-TP-CORE", school_id="TP-CORE", core_plan=plan, core_start_fy=FY
        )

        self.assertEqual(self.ledger().count("core_recruitment", None, *YEAR), 0)


class EvidenceTest(LedgerFixture):
    def ssa(self, school, status, day):
        return SsaRecord.objects.create(
            school=school,
            fy=FY,
            quarter="Q1",
            date_of_ssa=datetime(day.year, day.month, day.day, tzinfo=dt_tz.utc),
            average_score=6.0,
            verification_status=status,
            uploaded_by="test",
        )

    def test_an_uploaded_ssa_counts_before_confirmation_and_a_returned_one_never(self):
        """Owner, 2026-10-20: uploaded records "count once uploaded"."""
        self.ssa(self.client_school, "pending", date(2026, 11, 5))
        self.ssa(self.other, "returned", date(2026, 11, 5))

        ledger = self.ledger()

        self.assertEqual(ledger.count("ssa_client", None, *YEAR), 1)
        self.assertEqual(ledger.count("ssa_client", self.staff(self.mary), *YEAR), 0)

    def test_a_discipleship_club_is_a_confirmed_record_with_active_groups(self):
        for school, groups, status in (
            (self.client_school, 2, "confirmed"),
            (self.other, 0, "confirmed"),
            (self.core, 3, "returned"),
        ):
            DiscipleshipIndicatorRecord.objects.create(
                school=school,
                fy=FY,
                observed_on=date(2026, 11, 5),
                discipleship_groups_active=groups,
                recorded_by_user_id="ia",
                verification_status=status,
            )

        ledger = self.ledger()

        self.assertEqual(ledger.count("dc_clubs", None, *YEAR), 1)
        self.assertEqual(ledger.count("dc_data", None, *YEAR), 2)

    def test_exam_scores_and_onetest_are_read_by_assessment_type(self):
        for school, kind in (
            (self.core, "national_exam"),
            (self.client_school, "onetest"),
        ):
            LearningAssessmentResult.objects.create(
                school=school,
                fy=FY,
                assessment_type=kind,
                assessed_on=date(2026, 11, 5),
                grade_level="P7",
                subject="English",
                learners_tested=40,
                recorded_by_user_id="ia",
                verification_status="confirmed",
            )

        ledger = self.ledger()

        self.assertEqual(ledger.count("core_exam_scores", None, *YEAR), 1)
        self.assertEqual(ledger.count("onetest", None, *YEAR), 1)

    def test_enrolment_recorded_for_the_year(self):
        SchoolEnrollmentHistory.objects.create(
            school=self.client_school,
            fy=FY,
            enrollment=320,
            recorded_at=datetime(2026, 11, 5, tzinfo=dt_tz.utc),
        )

        self.assertEqual(self.ledger().count("enrolment", None, *YEAR), 1)

    def test_enrolment_uploaded_or_typed_on_the_profile_counts(self):
        """The school upload and the profile edit set the school's enrolment
        and its date, and write no history row: that date counts too."""
        School.objects.filter(pk=self.client_school.pk).update(
            enrollment=410, last_enrollment_date=date(2026, 12, 3)
        )
        School.objects.filter(pk=self.other.pk).update(
            enrollment=200,
            last_enrollment_date=date(2026, 9, 3),  # last year
        )

        ledger = self.ledger()

        self.assertEqual(ledger.count("enrolment", None, *YEAR), 1)
        self.assertEqual(ledger.count("enrolment", None, *month(12)), 1)
        self.assertEqual(ledger.count("schools_with_metrics", None, *YEAR), 1)

    def test_an_approved_story_counts_for_the_schools_owner(self):
        for status in ("approved", "submitted"):
            MostSignificantChangeStory.objects.create(
                user_id=str(self.mary.id),
                school=self.client_school,
                title="A story",
                narrative="…",
                story_date=date(2026, 11, 5),
                status=status,
            )

        ledger = self.ledger()

        self.assertEqual(ledger.count("msc", self.staff(self.james), *YEAR), 1)
        self.assertEqual(ledger.count("msc", self.staff(self.mary), *YEAR), 0)


class ProgrammesTest(LedgerFixture):
    def test_cluster_leaders_meetings_are_the_district_meetings_planned_and_held(
        self,
    ):
        """Owner, 2026-10-20: "cluster leader meeting should be fetched from
        the district meeting plan and completion"."""
        district = ActivityCatalogueItem.objects.get(
            stable_code="FIELD_DISTRICT_MEETING"
        )
        staff = {"responsible_staff_id": self.james.staff_profile.id}
        self.work(
            "field_event", day=date(2026, 11, 4), catalogue_item=district, **staff
        )
        self.work(
            "field_event",
            day=date(2027, 2, 9),
            status="scheduled",
            catalogue_item=district,
            **staff,
        )
        self.work(
            "field_event",
            day=date(2026, 11, 6),
            status="cancelled",
            catalogue_item=district,
            **staff,
        )
        # A cluster meeting held as a Cluster Leaders Meeting counts too.
        self.work(
            "cluster_meeting",
            day=date(2026, 12, 1),
            meeting_kind="cluster_leaders",
            **staff,
        )
        self.work(
            "cluster_meeting",
            day=date(2026, 12, 2),
            meeting_kind="only_meeting",
            **staff,
        )

        ledger = self.ledger()
        james = self.staff(self.james)

        self.assertEqual(ledger.count("cluster_leaders_meetings", james, *YEAR), 2)
        self.assertEqual(ledger.planned("cluster_leaders_meetings", james, *YEAR), 3)
        self.assertEqual(ledger.count("cluster_leaders_meetings", None, *month(11)), 1)

    def test_a_camp_with_schools_listed_still_counts_as_a_camp(self):
        camp = ActivityCatalogueItem.objects.get(stable_code="STUDENT_LEADERSHIP_CAMPS")
        self.work(
            "youth_camp",
            day=date(2026, 12, 8),
            catalogue_item=camp,
            responsible_staff_id=self.james.staff_profile.id,
            attended_school_ids=[str(self.client_school.pk)],
        )

        ledger = self.ledger()

        self.assertEqual(ledger.count("student_camps", None, *YEAR), 1)
        self.assertEqual(ledger.planned("student_camps", None, *YEAR), 1)

    def test_alumni_data_is_the_alumni_projects_schools(self):
        """Owner, 2026-10-20: "Alumni data should be fetched from project"."""
        from apps.projects.models import Project

        alumni = Project.objects.create(
            code="TP-ALUMNI", name="Alumni", category="selective_limited"
        )
        other = Project.objects.create(
            code="TP-OTHER", name="DIP", category="selective_limited"
        )
        self.work(
            "school_visit",
            self.client_school,
            day=date(2026, 11, 3),
            project_id=alumni.id,
        )
        self.work(
            "school_visit",
            self.other,
            day=date(2026, 12, 3),
            status="scheduled",
            project_id=alumni.id,
        )
        self.work("school_visit", self.core, day=date(2026, 11, 3), project_id=other.id)

        ledger = self.ledger()

        self.assertEqual(ledger.count("alumni_data", None, *YEAR), 1)
        self.assertEqual(ledger.planned("alumni_data", None, *YEAR), 2)
        self.assertEqual(
            ledger.count("alumni_data", self.staff(self.james), *month(11)), 1
        )


class PortfolioTest(LedgerFixture):
    def test_the_portfolio_splits_core_client_and_active(self):
        self.school(
            "TP-CLOSED", self.james, "client", operational_status="permanently_closed"
        )

        ledger = self.ledger()
        james = self.staff(self.james)

        self.assertEqual(ledger.portfolio(james), 3)
        self.assertEqual(ledger.portfolio(james, "active"), 2)
        self.assertEqual(ledger.portfolio(james, "core"), 1)
        self.assertEqual(ledger.portfolio(james, "client"), 2)
        self.assertEqual(ledger.portfolio(None), 4)

    def test_a_school_added_or_uploaded_in_the_year_is_a_new_school(self):
        """Owner, 2026-10-20: "any new school added or uploaded should be
        counted as new school and count towards the target of new schools"."""
        added = datetime(2026, 11, 7, 9, tzinfo=dt_tz.utc)
        School.objects.filter(pk=self.other.pk).update(created_at=added)
        School.objects.filter(pk__in=(self.core.pk, self.client_school.pk)).update(
            created_at=datetime(2026, 3, 2, tzinfo=dt_tz.utc)  # last year
        )
        # An orientation is a training, not a new school.
        self.work(
            "in_school_training",
            self.client_school,
            day=date(2026, 11, 9),
            catalogue_item=ActivityCatalogueItem.objects.get(
                stable_code="NEW_SCHOOL_ORIENTATION"
            ),
        )

        ledger = self.ledger()

        self.assertEqual(ledger.count("new_schools", None, *YEAR), 1)
        self.assertEqual(ledger.count("new_schools", None, *month(11)), 1)
        self.assertEqual(ledger.count("new_schools", self.staff(self.mary), *YEAR), 1)
        self.assertEqual(ledger.count("new_schools", self.staff(self.james), *YEAR), 0)
        self.assertIsNone(ledger.planned("new_schools", None, *YEAR))

    def test_an_owner_written_as_the_user_id_is_the_same_officer(self):
        School.objects.filter(pk=self.other.pk).update(account_owner_id=self.mary.id)

        self.assertEqual(self.ledger().portfolio(self.staff(self.mary)), 1)
