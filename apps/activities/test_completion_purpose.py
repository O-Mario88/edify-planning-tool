"""The Complete drawer asks what a visit was for, and takes the SSA (owner,
2026-10-20).

"activity completion should add SSA Support and In-school training", "add
ssa data entry field to the in-school visit ... with "ssa data collected"
and "No, Not Collected" Radio buttons", "School Visit + SSA Collection ...
make sure it has the same drawer as the ssa support and in-school training",
and "the activity completion drawer should have all the options for purpose
(SSA support, In-school training, Training Follow up)". Asked what choosing
In-school Training at completion means, the owner chose: ask which training
was delivered and create it beside the visit as its pair.

Pinned here:

  1. The drawer offers the three purposes on a visit whose purpose decides
     what it is, opened on the one it holds, and the SSA radios read "SSA
     data collected" / "No, not collected".
  2. A visit completed as SSA Support takes the purpose in place and keeps
     its scores against itself.
  3. A visit completed as an In-school Training stays the one activity, the
     pair's School Visit, and the training is created beside it: both are
     completed with their own IDs.
  4. A completion refused part-way changes nothing: the purpose stays, no
     training is created, no scores are kept.
  5. An In-school Training's drawer takes the SSA, and the scores are
     recorded on its school visit.
  6. A "School Visit + SSA Collection" opens the SSA Support drawer: the
     scores and its Visit ID.
"""

from __future__ import annotations

from django.test import Client

from apps.activities.models import Activity
from apps.activities.test_visit_purpose_change import _Fixture
from apps.core.enums import SsaIntervention
from apps.planning.services import schedule_in_school_training_pair
from apps.ssa.models import SsaRecord

HANDED_IN = ("submitted_to_pl", "awaiting_ia_verification", "ia_verified")


def _scores(value="6") -> dict:
    return {f"score_{code}": value for code, _label in SsaIntervention.choices}


def _a_course_id() -> str:
    from apps.activity_catalogue.availability import (
        in_school_training_course_options,
    )

    return in_school_training_course_options()[0]["id"]


class _Drawer(_Fixture):
    def _client(self):
        client = Client()
        client.force_login(self.cceo)
        return client

    def _drawer(self, activity):
        return self._client().get(
            f"/my-plan/{activity.id}/complete-drawer", headers={"HX-Request": "true"}
        )

    def _complete(self, activity, **posted):
        return self._client().post(
            f"/my-plan/{activity.id}/complete",
            posted,
            headers={"HX-Request": "true"},
        )


class TheDrawerOffersEveryPurpose(_Drawer):
    def test_a_follow_up_visit_is_offered_the_three_purposes(self):
        visit = self._follow_up()
        response = self._drawer(visit)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'name="purpose_type"')
        for value in ("ssa_support", "in_school_training", "training_follow_up"):
            self.assertContains(response, f'value="{value}"')
        self.assertContains(response, 'value="training_follow_up" selected')
        self.assertContains(response, 'name="training_course_id"')
        self.assertContains(response, 'name="training_salesforce_id"')

    def test_the_ssa_radios_say_what_they_mean(self):
        response = self._drawer(self._follow_up())
        self.assertContains(response, "SSA data collected")
        self.assertContains(response, "No, not collected")

    def test_an_activity_that_is_not_a_purpose_visit_is_offered_none(self):
        response = self._drawer(self._visit())
        self.assertNotContains(response, 'name="purpose_type"')


class CompletedAsSsaSupport(_Drawer):
    def test_the_visit_takes_the_purpose_and_keeps_its_scores(self):
        visit = self._follow_up()
        before = Activity.objects.count()

        response = self._complete(
            visit,
            purpose_type="ssa_support",
            ssa_collected="yes",
            salesforce_id="SVE-6101",
            **_scores(),
        )

        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(Activity.objects.count(), before)
        visit.refresh_from_db()
        self.assertEqual(visit.purpose_type, "ssa_support")
        self.assertEqual(visit.activity_type, "school_visit_ssa_collection")
        self.assertEqual(visit.salesforce_activity_id, "SVE-6101")
        self.assertIn(visit.status, HANDED_IN)
        self.assertTrue(
            SsaRecord.objects.filter(
                source_activity_id=visit.id, deleted_at__isnull=True
            ).exists()
        )


class CompletedAsAnInSchoolTraining(_Drawer):
    def _as_training(self, visit, **extra):
        posted = {
            "purpose_type": "in_school_training",
            "training_course_id": _a_course_id(),
            "teachers_attended": "6",
            "leaders_attended": "1",
            "training_salesforce_id": "TS-6201",
            "salesforce_id": "SVE-6201",
        }
        posted.update(extra)
        return self._complete(visit, **posted)

    def test_the_visit_becomes_the_pair_s_visit_and_the_training_is_created(self):
        visit = self._follow_up()
        before = Activity.objects.count()

        response = self._as_training(visit)

        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(Activity.objects.count(), before + 1)
        visit.refresh_from_db()
        training = Activity.objects.get(paired_school_visit_id=visit.id)
        self.assertEqual(visit.activity_type, "school_visit")
        self.assertEqual(visit.purpose_type, "in_school_training_delivery_visit")
        self.assertEqual(visit.salesforce_activity_id, "SVE-6201")
        self.assertIn(visit.status, HANDED_IN)
        self.assertEqual(training.activity_type, "in_school_training")
        self.assertEqual(training.school_id, visit.school_id)
        self.assertEqual(training.planned_date, visit.planned_date)
        self.assertEqual(training.responsible_staff_id, visit.responsible_staff_id)
        self.assertEqual(training.training_course_id, _a_course_id())
        self.assertEqual(training.salesforce_activity_id, "TS-6201")
        self.assertEqual(training.teachers_attended, 6)
        self.assertIn(training.status, HANDED_IN)

    def test_a_refused_training_id_changes_nothing(self):
        visit = self._follow_up()
        before = Activity.objects.count()

        response = self._as_training(visit, training_salesforce_id="NOT-AN-ID")

        self.assertContains(response, "TS-", status_code=400)
        self.assertEqual(Activity.objects.count(), before)
        visit.refresh_from_db()
        self.assertEqual(visit.purpose_type, "training_follow_up")
        self.assertEqual(visit.activity_type, "training_follow_up_visit")
        self.assertFalse(visit.salesforce_activity_id)

    def test_it_asks_which_training(self):
        visit = self._follow_up()
        response = self._as_training(visit, training_course_id="")
        self.assertContains(response, "Select the training delivered", status_code=400)
        visit.refresh_from_db()
        self.assertEqual(visit.purpose_type, "training_follow_up")


class ARefusedCompletionKeepsNoScores(_Drawer):
    def test_scores_go_with_the_completion_they_came_with(self):
        visit = self._follow_up()
        response = self._complete(
            visit,
            purpose_type="ssa_support",
            ssa_collected="yes",
            salesforce_id="NOT-AN-ID",
            **_scores(),
        )
        self.assertContains(response, "SV-", status_code=400)
        self.assertFalse(SsaRecord.objects.filter(source_activity_id=visit.id).exists())
        visit.refresh_from_db()
        self.assertEqual(visit.purpose_type, "training_follow_up")


class AnInSchoolTrainingTakesTheSsa(_Drawer):
    def _pair(self):
        from apps.activities.test_activity_editing import _weekday

        with self.captureOnCommitCallbacks(execute=True):
            created = schedule_in_school_training_pair(
                {
                    "schoolId": self.fresh_two.school_id,
                    "catalogueItemId": _a_course_id(),
                    "scheduledDate": _weekday(6).isoformat(),
                    "responsibleStaffId": str(self.cceo_staff.id),
                },
                self.cceo,
            )
        return (
            Activity.objects.get(id=created["id"]),
            Activity.objects.get(id=created["pairedSchoolVisitId"]),
        )

    def test_the_drawer_asks_for_the_scores_and_leaves_the_choice_open(self):
        training, _visit = self._pair()
        response = self._drawer(training)
        self.assertContains(response, "data-ssa-section")
        self.assertContains(response, "SSA data collected")
        self.assertNotContains(response, 'x-model="ssaCollected" checked')
        self.assertNotContains(response, 'name="ssa_not_collected_reason"')
        self.assertNotContains(response, 'name="purpose_type"')

    def test_the_scores_are_recorded_on_the_school_visit(self):
        training, visit = self._pair()
        response = self._complete(
            training,
            ssa_collected="yes",
            teachers_attended="4",
            salesforce_id="TS-6301",
            visit_salesforce_id="SVE-6301",
            **_scores("7"),
        )
        self.assertEqual(response.status_code, 200, response.content)
        record = SsaRecord.objects.get(source_activity_id=visit.id)
        self.assertEqual(record.school_id, visit.school_id)
        training.refresh_from_db()
        self.assertIn(training.status, HANDED_IN)

    def test_it_completes_without_scores(self):
        training, visit = self._pair()
        response = self._complete(
            training,
            ssa_collected="no",
            teachers_attended="4",
            salesforce_id="TS-6302",
            visit_salesforce_id="SVE-6302",
        )
        self.assertEqual(response.status_code, 200, response.content)
        self.assertFalse(SsaRecord.objects.filter(source_activity_id=visit.id).exists())
        visit.refresh_from_db()
        self.assertIn(visit.status, HANDED_IN)


class ASchoolVisitWithSsaCollection(_Drawer):
    def _ssa_visit(self):
        visit = self._follow_up()
        self._change(visit, "ssa_support")
        visit.refresh_from_db()
        self.assertEqual(visit.activity_name_snapshot, "School Visit + SSA Collection")
        return visit

    def test_it_opens_the_ssa_support_drawer(self):
        response = self._drawer(self._ssa_visit())
        self.assertContains(response, "data-ssa-section")
        self.assertContains(response, 'value="ssa_support" selected')
        self.assertContains(response, 'name="salesforce_id"')
        self.assertContains(response, "Visit ID")

    def test_it_completes_with_its_scores_and_visit_id(self):
        visit = self._ssa_visit()
        response = self._complete(
            visit,
            purpose_type="ssa_support",
            ssa_collected="yes",
            salesforce_id="SV-6401",
            **_scores(),
        )
        self.assertEqual(response.status_code, 200, response.content)
        visit.refresh_from_db()
        self.assertEqual(visit.salesforce_activity_id, "SV-6401")
        self.assertIn(visit.status, HANDED_IN)
        self.assertTrue(SsaRecord.objects.filter(source_activity_id=visit.id).exists())

    def test_an_older_one_with_no_purpose_reads_as_ssa_support(self):
        visit = self._ssa_visit()
        Activity.objects.filter(id=visit.id).update(purpose_type=None)
        response = self._drawer(visit)
        self.assertContains(response, 'value="ssa_support" selected')
        self._complete(visit, purpose_type="ssa_support", salesforce_id="SV-6402")
        visit.refresh_from_db()
        self.assertIsNone(visit.purpose_type)
        self.assertEqual(visit.salesforce_activity_id, "SV-6402")


class DeliveredAsAnInSchoolTrainingWithTheSsa(_Drawer):
    """Owner, 2026-10-20: "School Visit + SSA Collection — since they are
    doing in-school training, you should make sure the purpose is in-school
    training and ssa collection"."""

    def _ssa_visit(self):
        visit = self._follow_up()
        self._change(visit, "ssa_support")
        visit.refresh_from_db()
        return visit

    def test_the_drawer_names_the_training_and_the_collection(self):
        response = self._drawer(self._ssa_visit())
        self.assertContains(response, "In-school Training + SSA Collection")

    def test_it_completes_as_both_with_the_scores_on_the_visit(self):
        visit = self._ssa_visit()
        response = self._complete(
            visit,
            purpose_type="in_school_training_ssa",
            training_course_id=_a_course_id(),
            teachers_attended="5",
            training_salesforce_id="TS-6501",
            salesforce_id="SVE-6501",
            ssa_collected="yes",
            **_scores("8"),
        )
        self.assertEqual(response.status_code, 200, response.content)
        visit.refresh_from_db()
        training = Activity.objects.get(paired_school_visit_id=visit.id)
        self.assertEqual(training.salesforce_activity_id, "TS-6501")
        self.assertEqual(visit.salesforce_activity_id, "SVE-6501")
        self.assertTrue(visit.ssa_collection_expected)
        self.assertTrue(SsaRecord.objects.filter(source_activity_id=visit.id).exists())
        self.assertFalse(
            SsaRecord.objects.filter(source_activity_id=training.id).exists()
        )

    def test_a_training_id_in_the_visit_id_says_where_it_goes(self):
        visit = self._ssa_visit()
        response = self._complete(
            visit, purpose_type="ssa_support", salesforce_id="TS-6502"
        )
        self.assertContains(response, "is a training ID", status_code=400)
        self.assertContains(
            response, "In-school Training + SSA Collection", status_code=400
        )
        visit.refresh_from_db()
        self.assertFalse(visit.salesforce_activity_id)


class TheEditDrawerMakesItAnInSchoolTraining(_Drawer):
    """The Edit drawer offers In-school Training too, and asks which
    training (owner, 2026-10-20: "test activity edit as well. Also, if it is
    inschool training, the training name has to be selected")."""

    def _edit(self, visit, **posted):
        return self._client().post(
            f"/my-plan/{visit.id}/edit",
            {"reason": "A training was delivered", **posted},
            headers={"HX-Request": "true"},
        )

    def test_it_offers_in_school_training_and_asks_which_training(self):
        response = self._client().get(f"/my-plan/{self._follow_up().id}/edit-drawer")
        self.assertContains(response, 'value="in_school_training"')
        self.assertContains(response, 'name="purpose_training_course_id"')
        self.assertContains(response, "Which training?")

    def test_the_training_name_has_to_be_selected(self):
        visit = self._follow_up()
        response = self._edit(visit, purpose_type="in_school_training")
        self.assertContains(response, "Select the training delivered", status_code=400)
        visit.refresh_from_db()
        self.assertEqual(visit.purpose_type, "training_follow_up")
        self.assertFalse(Activity.objects.filter(paired_school_visit=visit).exists())

    def test_the_visit_becomes_the_pair_s_visit_with_the_training_named(self):
        from apps.audit.models import AuditLog

        visit = self._follow_up()
        response = self._edit(
            visit,
            purpose_type="in_school_training",
            purpose_training_course_id=_a_course_id(),
        )
        self.assertEqual(response.status_code, 200, response.content)
        visit.refresh_from_db()
        training = Activity.objects.get(paired_school_visit_id=visit.id)
        self.assertEqual(visit.status, "scheduled")
        self.assertEqual(visit.activity_type, "school_visit")
        self.assertEqual(visit.purpose_type, "in_school_training_delivery_visit")
        self.assertEqual(training.training_course_id, _a_course_id())
        self.assertEqual(training.planned_date, visit.planned_date)
        self.assertEqual(training.status, "scheduled")
        self.assertTrue(visit.schedule_cost_lines.exists())
        entry = AuditLog.objects.get(
            action="activity.purpose_changed", subject_id=visit.id
        )
        self.assertEqual(entry.payload["to"]["trainingActivityId"], training.id)
        self.assertEqual(entry.reason, "A training was delivered")

    def test_the_pair_then_completes_with_both_ids(self):
        visit = self._follow_up()
        self._edit(
            visit,
            purpose_type="in_school_training",
            purpose_training_course_id=_a_course_id(),
        )
        training = Activity.objects.get(paired_school_visit_id=visit.id)
        response = self._complete(
            training,
            teachers_attended="3",
            salesforce_id="TS-6601",
            visit_salesforce_id="SVE-6601",
        )
        self.assertEqual(response.status_code, 200, response.content)
        training.refresh_from_db()
        visit.refresh_from_db()
        self.assertEqual(training.salesforce_activity_id, "TS-6601")
        self.assertEqual(visit.salesforce_activity_id, "SVE-6601")

    def test_an_ssa_visit_is_offered_the_training_with_its_collection(self):
        visit = self._follow_up()
        self._change(visit, "ssa_support")
        response = self._client().get(f"/my-plan/{visit.id}/edit-drawer")
        self.assertContains(response, "In-school Training + SSA Collection")


class TwoTrainingPurposes(_Drawer):
    """In-school Training and In-school Training + SSA Collection are two
    options (owner, 2026-10-20), offered at completion and in Edit."""

    def test_both_are_offered_at_completion_and_in_edit(self):
        visit = self._follow_up()
        for url in (
            f"/my-plan/{visit.id}/complete-drawer",
            f"/my-plan/{visit.id}/edit-drawer",
        ):
            response = self._client().get(url, headers={"HX-Request": "true"})
            self.assertContains(response, 'value="in_school_training"')
            self.assertContains(response, 'value="in_school_training_ssa"')

    def _edit_to(self, visit, purpose):
        return self._client().post(
            f"/my-plan/{visit.id}/edit",
            {
                "reason": "A training was delivered",
                "purpose_type": purpose,
                "purpose_training_course_id": _a_course_id(),
            },
            headers={"HX-Request": "true"},
        )

    def test_with_ssa_collection_the_visit_collects_it(self):
        visit = self._follow_up()
        response = self._edit_to(visit, "in_school_training_ssa")
        self.assertEqual(response.status_code, 200, response.content)
        visit.refresh_from_db()
        self.assertTrue(visit.ssa_collection_expected)
        training = Activity.objects.get(paired_school_visit_id=visit.id)
        self.assertFalse(training.ssa_collection_expected)

    def test_without_it_the_visit_does_not(self):
        visit = self._follow_up()
        self._change(visit, "ssa_support")
        response = self._edit_to(visit, "in_school_training")
        self.assertEqual(response.status_code, 200, response.content)
        visit.refresh_from_db()
        self.assertFalse(visit.ssa_collection_expected)
        self.assertTrue(Activity.objects.filter(paired_school_visit=visit).exists())

    def test_the_pair_drawer_of_a_collecting_visit_opens_on_collected(self):
        visit = self._follow_up()
        self._edit_to(visit, "in_school_training_ssa")
        training = Activity.objects.get(paired_school_visit_id=visit.id)
        response = self._drawer(training)
        self.assertContains(response, 'x-model="ssaCollected" checked')
        self.assertContains(response, 'name="ssa_not_collected_reason"')


class ACoreVisitBecomesAnInSchoolTraining(_Drawer):
    """Owner, 2026-10-20 (asked whether Core visits offer the In-school
    Training purposes too): "Yes, take a training slot". The training takes
    the package's next open training slot; the visit keeps its own."""

    def setUp(self):
        super().setUp()
        from apps.accounts.models import StaffSchoolAssignment
        from apps.activities.test_activity_editing import _weekday
        from apps.core.fy import get_operational_fy
        from apps.core_schools.models import CorePlan, cplan_id
        from apps.core_schools.services import create_package_slots
        from apps.schools.models import School

        self.day = _weekday(8)
        self.fy = get_operational_fy(self.day)
        self.core = School.objects.create(
            school_id="PURPOSE-CORE",
            name="Purpose Core",
            region=self.region,
            district=self.district,
            school_type="core",
            account_owner_id=self.cceo_staff.id,
        )
        StaffSchoolAssignment.objects.create(
            staff=self.cceo_staff, school_id=self.core.id
        )
        self.plan = CorePlan.objects.create(
            id=cplan_id("PURPOSE-CORE", fy=self.fy),
            school_id="PURPOSE-CORE",
            fy=self.fy,
            status="Active",
        )
        create_package_slots(self.plan, "PURPOSE-CORE", ["leadership"])
        with self.captureOnCommitCallbacks(execute=True):
            self.visit = Activity.objects.create(
                activity_type="core_visit",
                purpose_type="ssa_support",
                ssa_collection_expected=True,
                status="scheduled",
                delivery_type="staff",
                fy=self.fy,
                quarter="Q1",
                planned_date=self.day,
                school=self.core,
                responsible_staff_id=str(self.cceo_staff.id),
                activity_purpose_text="Core School Assessment",
            )

    def _slot_of(self, activity):
        from apps.core_schools.models import CoreActivitySlot

        return CoreActivitySlot.objects.filter(activity_id=activity.id).first()

    def test_the_drawers_offer_the_training_purposes(self):
        for url in (
            f"/my-plan/{self.visit.id}/complete-drawer",
            f"/my-plan/{self.visit.id}/edit-drawer",
        ):
            response = self._client().get(url, headers={"HX-Request": "true"})
            for value in (
                "ssa_support",
                "training_follow_up",
                "in_school_training",
                "in_school_training_ssa",
            ):
                self.assertContains(response, f'value="{value}"')

    def test_the_training_takes_a_training_slot_and_the_visit_keeps_its_own(self):
        visit_slot = self._slot_of(self.visit)
        self.assertEqual(visit_slot.activity_type, "visit")
        with self.captureOnCommitCallbacks(execute=True):
            response = self._client().post(
                f"/my-plan/{self.visit.id}/edit",
                {
                    "reason": "A training was delivered",
                    "purpose_type": "in_school_training_ssa",
                    "purpose_training_course_id": _a_course_id(),
                },
                headers={"HX-Request": "true"},
            )
        self.assertEqual(response.status_code, 200, response.content)
        self.visit.refresh_from_db()
        training = Activity.objects.get(paired_school_visit_id=self.visit.id)
        self.assertEqual(self.visit.activity_type, "school_visit")
        self.assertTrue(self.visit.ssa_collection_expected)
        self.assertEqual(self._slot_of(self.visit).id, visit_slot.id)
        training_slot = self._slot_of(training)
        self.assertIsNotNone(training_slot)
        self.assertEqual(training_slot.activity_type, "training")
        self.assertEqual(training_slot.core_plan_id, self.plan.id)
