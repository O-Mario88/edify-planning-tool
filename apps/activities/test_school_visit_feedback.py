from datetime import date
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase

from apps.accounts.models import (
    StaffGeographyAssignment,
    StaffProfile,
    StaffSchoolAssignment,
)
from apps.activities.models import Activity, SchoolVisitFeedback
from apps.activities.services import complete
from apps.core.exceptions import BadRequest
from apps.core.rbac import EdifyRole
from apps.frontend.views.visit_effectiveness_views import _visit_feedback_review
from apps.geography.models import District, Region
from apps.schools.models import School


class SchoolVisitFeedbackTest(TestCase):
    def setUp(self):
        self.region = Region.objects.create(name="Feedback Region", country="Uganda")
        self.district = District.objects.create(
            name="Feedback District", region=self.region
        )
        self.school = School.objects.create(
            school_id="FB-SCHOOL-1",
            name="Feedback Academy",
            region=self.region,
            district=self.district,
        )
        self.cceo, self.cceo_staff = self._staff_user(
            "feedback-cceo@example.org", EdifyRole.CCEO
        )
        StaffSchoolAssignment.objects.create(
            staff=self.cceo_staff, school_id=self.school.id
        )
        self.training = Activity.objects.create(
            school=self.school,
            activity_type="in_school_training",
            status="ia_verified",
            responsible_staff_id=self.cceo_staff.id,
            fy="2026",
            quarter="Q3",
            planned_date=date(2026, 8, 1),
        )
        self.visit = Activity.objects.create(
            school=self.school,
            activity_type="school_visit",
            status="completion_started",
            responsible_staff_id=self.cceo_staff.id,
            follow_up_of_activity=self.training,
            fy="2026",
            quarter="Q3",
            planned_date=date(2026, 9, 1),
        )

    def _staff_user(self, email, role):
        user = get_user_model().objects.create_user(
            email=email,
            name=role.value,
            roles=[role.value],
            active_role=role.value,
            password="x",
            is_active=True,
        )
        profile = StaffProfile.objects.create(
            user=user, title=role.value, country="Uganda"
        )
        return user, profile

    def _feedback(self):
        return SchoolVisitFeedback.objects.create(
            activity=self.visit,
            finding="Attendance registers were current and classrooms were orderly.",
            improvements=[
                "Attendance is reviewed weekly",
                "Two classrooms have new desks",
            ],
            recorded_by=self.cceo.id,
        )

    def test_completion_drawer_requires_finding_and_improvement_list(self):
        self.client.force_login(self.cceo)
        response = self.client.get(
            f"/my-plan/{self.visit.id}/complete-drawer",
            HTTP_HX_REQUEST="true",
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'name="feedback_finding"')
        self.assertContains(response, 'name="school_improvements"')
        self.assertContains(response, "what you found on the ground")
        self.assertContains(response, "one improvement per line")

    def test_visit_completion_rejects_missing_feedback(self):
        with self.assertRaisesMessage(BadRequest, "what you found on the ground"):
            complete(
                self.visit.id,
                {"salesforceId": "SVE-FEEDBACK-MISSING", "strict_validation": True},
                self.cceo,
            )

        self.assertFalse(SchoolVisitFeedback.objects.exists())

    @patch("apps.evidence.requirements.missing_evidence_kinds", return_value=[])
    @patch("apps.evidence.requirements.evidence_optional", return_value=True)
    def test_visit_completion_stores_normalized_structured_feedback(
        self, _evidence_optional, _missing_evidence
    ):
        complete(
            self.visit.id,
            {
                "salesforceId": "SVE-FEEDBACK-1",
                "strict_validation": True,
                "feedbackFinding": "  Leaders are using the lesson tracker.  ",
                "schoolImprovements": [
                    "- Weekly lesson reviews",
                    "2. Parent attendance has increased",
                    "",
                ],
            },
            self.cceo,
        )

        feedback = SchoolVisitFeedback.objects.get(activity=self.visit)
        self.assertEqual(feedback.finding, "Leaders are using the lesson tracker.")
        self.assertEqual(
            feedback.improvements,
            ["Weekly lesson reviews", "Parent attendance has increased"],
        )
        self.assertEqual(feedback.recorded_by, self.cceo.id)

    def test_school_profile_shows_feedback_and_related_training(self):
        self._feedback()
        self.client.force_login(self.cceo)

        response = self.client.get(f"/schools/{self.school.school_id}")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "School Visit Feedback")
        self.assertContains(response, "Attendance registers were current")
        self.assertContains(response, "Attendance is reviewed weekly")
        self.assertContains(response, "Related to In-school Training")

    def test_ia_cd_pl_and_rvp_receive_role_scoped_review_context(self):
        self._feedback()
        ia, _ = self._staff_user("feedback-ia@example.org", EdifyRole.IMPACT_ASSESSMENT)
        cd, _ = self._staff_user("feedback-cd@example.org", EdifyRole.COUNTRY_DIRECTOR)
        pl, pl_staff = self._staff_user(
            "feedback-pl@example.org", EdifyRole.COUNTRY_PROGRAM_LEAD
        )
        StaffSchoolAssignment.objects.create(staff=pl_staff, school_id=self.school.id)
        rvp, rvp_staff = self._staff_user(
            "feedback-rvp@example.org", EdifyRole.REGIONAL_VICE_PRESIDENT
        )
        StaffGeographyAssignment.objects.create(
            staff=rvp_staff, region_id=self.region.id
        )

        for reviewer in (ia, cd, pl, rvp):
            with self.subTest(role=reviewer.active_role):
                rows = _visit_feedback_review(reviewer)
                self.assertEqual(len(rows), 1)
                self.assertEqual(rows[0]["feedback"].finding, self._feedback_text())
                self.assertEqual(rows[0]["related_activity"], self.training)

        self.assertEqual(
            _visit_feedback_review(rvp)[0]["school_name"],
            "School identity protected",
        )
        self.assertEqual(_visit_feedback_review(rvp)[0]["school_id"], "")
        self.assertEqual(_visit_feedback_review(ia)[0]["school_name"], self.school.name)

    def test_rvp_can_read_feedback_in_visit_effectiveness_without_school_identity(self):
        self._feedback()
        rvp, rvp_staff = self._staff_user(
            "feedback-rvp-page@example.org", EdifyRole.REGIONAL_VICE_PRESIDENT
        )
        StaffGeographyAssignment.objects.create(
            staff=rvp_staff, region_id=self.region.id
        )
        self.client.force_login(rvp)

        response = self.client.get("/analytics/visit-effectiveness")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Recent school visit feedback")
        self.assertContains(response, "Attendance registers were current")
        self.assertContains(response, "School identity protected")
        self.assertNotContains(response, self.school.name)

    @staticmethod
    def _feedback_text():
        return "Attendance registers were current and classrooms were orderly."
