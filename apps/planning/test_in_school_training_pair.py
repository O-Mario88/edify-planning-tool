"""One in-school Training decision creates and completes two governed records."""

from __future__ import annotations

from unittest.mock import patch

from django.test import Client

from apps.activities.models import Activity, ActivitySalesforceReference
from apps.activities.services import (
    complete_in_school_training_pair,
    start_in_school_training_pair,
)
from apps.activity_catalogue.availability import in_school_training_course_options
from apps.core.enums import EvidenceKind, SsaIntervention
from apps.core.exceptions import BadRequest
from apps.evidence.models import EvidenceRecord
from apps.planning.services import schedule_in_school_training_pair

from .test_standard_support_scheduling import (
    StandardSupportBase,
    _at,
    _schedulable_date,
)


class InSchoolTrainingPairTest(StandardSupportBase):
    def payload(self, course_code="TAM_I"):
        return {
            "schoolId": self.school.school_id,
            "catalogueItemId": self.item(course_code).id,
            "scheduledDate": _at(_schedulable_date()).isoformat(),
            "responsibleStaffId": self.staff.id,
            "deliveryType": "staff",
            "executorType": "staff",
            "requireCatalogue": True,
            "activityPurposeText": "Deliver the selected in-school course",
        }

    def test_in_school_picker_contains_all_21_courses_with_ssa_metadata(self):
        options = in_school_training_course_options(school=self.school)
        self.assertEqual(len(options), 21)
        by_code = {option["stableCode"]: option for option in options}
        self.assertEqual(
            by_code["TAM_I"]["ssaIntervention"],
            SsaIntervention.EXPOSURE_TO_WORD_OF_GOD,
        )
        self.assertEqual(by_code["TAM_I"]["category"], "Christian Transformation")
        self.assertEqual(by_code["NEW_SCHOOL_ORIENTATION"]["ssaIntervention"], "")

    def test_school_drawer_renders_cluster_and_school_course_titles(self):
        client = Client()
        client.force_login(self.user)
        response = client.get(
            f"/planning/schedule-modal?school_id={self.school.school_id}",
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(response.status_code, 200)
        html = response.content.decode("utf-8")
        self.assertIn("Teaching as Mission (TAM)", html)
        self.assertIn("EdTech Foundations Training", html)
        self.assertIn("New School Orientation", html)

    def test_schedule_action_routes_in_school_training_to_pair_service(self):
        client = Client()
        client.force_login(self.user)
        with patch(
            "apps.frontend.views.planning_views.schedule_in_school_training_pair",
            return_value={
                "id": "training-id",
                "pairedSchoolVisitId": "visit-id",
            },
        ) as schedule_pair:
            response = client.post(
                "/planning/schedule-action",
                {
                    "school_id": self.school.school_id,
                    "purpose_of_visit": "in_school_training",
                    "scheduled_date": str(_schedulable_date()),
                    "catalogue_item_id": self.item("TAM_I").id,
                    "require_catalogue": "yes",
                    "delivery_type": "staff",
                    "executor_type": "staff",
                },
                HTTP_HX_REQUEST="true",
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(schedule_pair.call_count, 1)
        payload = schedule_pair.call_args.args[0]
        self.assertEqual(payload["catalogueItemId"], self.item("TAM_I").id)
        self.assertEqual(
            payload["focusIntervention"],
            SsaIntervention.EXPOSURE_TO_WORD_OF_GOD,
        )

    def test_one_decision_creates_training_and_visit_with_course_identity(self):
        result = schedule_in_school_training_pair(self.payload(), self.user)

        training = Activity.objects.get(id=result["id"])
        visit = Activity.objects.get(id=result["pairedSchoolVisitId"])
        self.assertEqual(Activity.objects.filter(school=self.school).count(), 2)
        self.assertEqual(training.activity_type, "in_school_training")
        self.assertEqual(training.training_course.stable_code, "TAM_I")
        self.assertEqual(
            training.catalogue_item.stable_code, "STANDARD_IN_SCHOOL_TRAINING"
        )
        self.assertEqual(training.activity_name_snapshot, "Teaching as Mission (TAM)")
        self.assertEqual(
            training.focus_intervention,
            SsaIntervention.EXPOSURE_TO_WORD_OF_GOD,
        )
        self.assertEqual(training.paired_school_visit_id, visit.id)
        self.assertEqual(visit.activity_type, "school_visit")
        self.assertEqual(visit.catalogue_item.stable_code, "STANDARD_SCHOOL_VISIT")
        self.assertEqual(visit.school_id, training.school_id)
        self.assertEqual(visit.planned_date, training.planned_date)
        self.assertEqual(visit.responsible_staff_id, training.responsible_staff_id)
        self.assertEqual(visit.focus_intervention, training.focus_intervention)

    def test_administrative_course_does_not_invent_an_ssa_intervention(self):
        result = schedule_in_school_training_pair(
            self.payload("NEW_SCHOOL_ORIENTATION"), self.user
        )
        training = Activity.objects.get(id=result["id"])
        visit = Activity.objects.get(id=result["pairedSchoolVisitId"])
        self.assertIsNone(training.focus_intervention)
        self.assertIsNone(visit.focus_intervention)

    def test_a_failure_creating_visit_rolls_back_training(self):
        before = Activity.objects.count()
        real_create = __import__("apps.activities.services", fromlist=["create"]).create
        calls = 0

        def fail_second(*args, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise BadRequest("Visit could not be created.")
            return real_create(*args, **kwargs)

        with patch("apps.activities.services.create", side_effect=fail_second):
            with self.assertRaisesMessage(BadRequest, "Visit could not be created"):
                schedule_in_school_training_pair(self.payload(), self.user)
        self.assertEqual(Activity.objects.count(), before)

    def _scheduled_pair_ready_for_completion(self):
        result = schedule_in_school_training_pair(self.payload(), self.user)
        training = Activity.objects.get(id=result["id"])
        visit = Activity.objects.get(id=result["pairedSchoolVisitId"])
        for activity, kind in (
            (training, EvidenceKind.ATTENDANCE_FORM),
            (visit, EvidenceKind.VISIT_FORM),
        ):
            EvidenceRecord.objects.create(
                activity=activity,
                kind=kind,
                uri=f"{activity.id}.pdf",
                original_name=f"{kind}.pdf",
                mime_type="application/pdf",
                uploaded_by=self.user.id,
                uploader_role=self.user.active_role,
                quarantined=False,
            )
        start_in_school_training_pair(training.id, self.user)
        return training, visit

    def test_both_salesforce_ids_and_statuses_are_committed_together(self):
        training, visit = self._scheduled_pair_ready_for_completion()
        complete_in_school_training_pair(
            training.id,
            {
                "trainingSalesforceId": "TS-PAIR-1001",
                "visitSalesforceId": "SVE-PAIR-1001",
                "teachersAttended": 4,
                "leadersAttended": 1,
            },
            self.user,
        )
        training.refresh_from_db()
        visit.refresh_from_db()
        self.assertEqual(training.salesforce_activity_id, "TS-PAIR-1001")
        self.assertEqual(visit.salesforce_activity_id, "SVE-PAIR-1001")
        self.assertEqual(training.status, "submitted_to_pl")
        self.assertEqual(visit.status, "submitted_to_pl")
        self.assertEqual(
            ActivitySalesforceReference.objects.filter(
                activity_id__in=[training.id, visit.id]
            ).count(),
            2,
        )

    def test_invalid_visit_id_rolls_back_training_salesforce_reservation(self):
        training, visit = self._scheduled_pair_ready_for_completion()
        with self.assertRaisesMessage(BadRequest, "SVE-"):
            complete_in_school_training_pair(
                training.id,
                {
                    "trainingSalesforceId": "TS-PAIR-ROLLBACK",
                    "visitSalesforceId": "SV-WRONG-PREFIX",
                    "teachersAttended": 2,
                    "leadersAttended": 0,
                },
                self.user,
            )
        training.refresh_from_db()
        visit.refresh_from_db()
        self.assertEqual(training.status, "completion_started")
        self.assertEqual(visit.status, "completion_started")
        self.assertIsNone(training.salesforce_activity_id)
        self.assertIsNone(visit.salesforce_activity_id)
        self.assertFalse(
            ActivitySalesforceReference.objects.filter(
                activity_id__in=[training.id, visit.id]
            ).exists()
        )

    def test_completion_drawer_exposes_both_ids_and_both_evidence_inputs(self):
        result = schedule_in_school_training_pair(self.payload(), self.user)
        client = Client()
        client.force_login(self.user)
        response = client.get(
            f"/my-plan/{result['id']}/complete-drawer",
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(response.status_code, 200)
        html = response.content.decode("utf-8")
        self.assertIn('name="salesforce_id"', html)
        self.assertIn('name="visit_salesforce_id"', html)
        self.assertIn('name="training_evidence_file"', html)
        self.assertIn('name="visit_evidence_file"', html)
        self.assertIn("Submit Training + Visit", html)
