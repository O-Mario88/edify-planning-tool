"""School Visit + SSA Collection visits become In-school Training + SSA
Collection, and each names its training (owner, 2026-10-20).

"make sure all those who used "school visit + ssa collection" are changed to
In-school training + SSA Collection and they should be able to fetch the
training from the system. Everything should be updated on the training
summary, school visits ... everywhere." The owner chose: completed visits
stay as they are; a dry run first, then the migration.

Pinned here:

  1. The dry run lists what changes and what is left, and writes nothing.
  2. Applied, a staff visit still on the plan takes the purpose and the name,
     collects the SSA, and the change is audited; completed, partner and
     already-changed visits are left.
  3. A changed visit cannot be completed without its training, at any door:
     Complete, Submit, and the Salesforce ID sweep.
  4. Naming the training from the Complete drawer creates it beside the
     visit, as an In-school Training, and both complete with their IDs; Edit
     names it too, and a date-only edit still saves.
  5. An officer whose visit only collected the SSA completes it as SSA
     Support.
"""

from __future__ import annotations

import io

from django.core.management import call_command

from apps.activities import services
from apps.activities.models import Activity
from apps.activities.ssa_collection_to_training import (
    NEW_NAME,
    awaits_training,
    convert,
)
from apps.activities.test_completion_purpose import _a_course_id, _Drawer, _scores
from apps.audit.models import AuditLog
from apps.core.exceptions import BadRequest
from apps.ssa.models import SsaRecord

HANDED_IN = ("submitted_to_pl", "awaiting_ia_verification", "ia_verified")


class _Fixture(_Drawer):
    def _ssa_visit(self, **update):
        """A School Visit + SSA Collection as staff planned them."""
        visit = self._follow_up()
        self._change(visit, "ssa_support")
        if update:
            Activity.objects.filter(id=visit.id).update(**update)
        visit.refresh_from_db()
        self.assertEqual(visit.activity_type, "school_visit_ssa_collection")
        return visit

    def _converted(self, **update):
        visit = self._ssa_visit(**update)
        convert(apply=True)
        visit.refresh_from_db()
        return visit


class TheDryRun(_Fixture):
    def test_it_lists_and_writes_nothing(self):
        visit = self._ssa_visit()
        Activity.objects.filter(id=visit.id).update(status="scheduled")
        done = self._ssa_visit(status="submitted_to_pl")

        found = convert(apply=False)

        self.assertIn(visit.id, [row["id"] for row in found["converted"]])
        self.assertNotIn(done.id, [row["id"] for row in found["converted"]])
        self.assertIn(done.id, [row["id"] for row in found["left"]])
        visit.refresh_from_db()
        self.assertEqual(visit.purpose_type, "ssa_support")

    def test_the_command_is_a_dry_run_unless_told(self):
        visit = self._ssa_visit()
        call_command("convert_ssa_collection_visits", stdout=io.StringIO())
        visit.refresh_from_db()
        self.assertEqual(visit.purpose_type, "ssa_support")
        call_command("convert_ssa_collection_visits", "--apply", stdout=io.StringIO())
        visit.refresh_from_db()
        self.assertEqual(visit.purpose_type, "in_school_training_ssa")


class Applied(_Fixture):
    def test_an_open_visit_takes_the_purpose_and_the_name(self):
        visit = self._converted()
        self.assertEqual(visit.purpose_type, "in_school_training_ssa")
        self.assertEqual(visit.activity_name_snapshot, NEW_NAME)
        self.assertTrue(visit.ssa_collection_expected)
        self.assertEqual(visit.activity_type, "school_visit_ssa_collection")
        self.assertTrue(awaits_training(visit))
        entry = AuditLog.objects.get(
            action="activity.purpose_changed",
            subject_id=visit.id,
            payload__to__purposeType="in_school_training_ssa",
        )
        self.assertEqual(entry.payload["from"]["purposeType"], "ssa_support")

    def test_a_started_visit_is_changed(self):
        visit = self._converted(status="completion_started")
        self.assertEqual(visit.purpose_type, "in_school_training_ssa")

    def test_completed_and_partner_visits_are_left(self):
        done = self._converted(status="ia_verified")
        self.assertEqual(done.purpose_type, "ssa_support")
        partner = self._converted(delivery_type="partner")
        self.assertEqual(partner.purpose_type, "ssa_support")

    def test_running_it_again_changes_nothing_more(self):
        visit = self._converted()
        convert(apply=True)
        self.assertEqual(
            AuditLog.objects.filter(
                action="activity.purpose_changed",
                subject_id=visit.id,
                payload__to__purposeType="in_school_training_ssa",
            ).count(),
            1,
        )


class ItCannotBeCompletedWithoutItsTraining(_Fixture):
    def test_complete_refuses_it(self):
        visit = self._converted()
        services.start_completion(visit.id, principal=self.cceo)
        with self.assertRaises(BadRequest):
            services.complete(visit.id, {"salesforceId": "SVE-7701"}, self.cceo)
        visit.refresh_from_db()
        self.assertEqual(visit.status, "completion_started")

    def test_submit_refuses_it(self):
        visit = self._converted(status="completion_started")
        Activity.objects.filter(id=visit.id).update(salesforce_activity_id="SVE-7702")
        with self.assertRaises(BadRequest):
            services.submit_for_review(visit.id, self.cceo)

    def test_the_sweep_leaves_it(self):
        from apps.pl_review.handed_in import hand_in_entered_work

        visit = self._converted()
        Activity.objects.filter(id=visit.id).update(salesforce_activity_id="SVE-7703")
        self.assertNotIn(
            visit.id, [row["id"] for row in hand_in_entered_work(apply=True)]
        )
        visit.refresh_from_db()
        self.assertEqual(visit.status, "scheduled")

    def test_the_drawer_opens_on_it_and_asks_for_the_training(self):
        response = self._drawer(self._converted())
        self.assertContains(response, 'value="in_school_training_ssa" selected')
        self.assertContains(response, 'name="training_course_id"')
        self.assertContains(response, "data-ssa-section")

    def test_completing_it_without_naming_the_training_is_refused(self):
        visit = self._converted()
        response = self._complete(
            visit, purpose_type="in_school_training_ssa", salesforce_id="SVE-7704"
        )
        self.assertContains(response, "Select the training delivered", status_code=400)
        visit.refresh_from_db()
        self.assertFalse(visit.salesforce_activity_id)


class TheTrainingIsFetchedFromTheCatalogue(_Fixture):
    def test_completing_it_creates_the_training_and_completes_both(self):
        visit = self._converted()
        response = self._complete(
            visit,
            purpose_type="in_school_training_ssa",
            training_course_id=_a_course_id(),
            teachers_attended="7",
            training_salesforce_id="TS-7801",
            salesforce_id="SVE-7801",
            ssa_collected="yes",
            **_scores(),
        )
        self.assertEqual(response.status_code, 200, response.content)
        visit.refresh_from_db()
        training = Activity.objects.get(paired_school_visit_id=visit.id)
        self.assertEqual(training.activity_type, "in_school_training")
        self.assertEqual(training.training_course_id, _a_course_id())
        self.assertEqual(training.salesforce_activity_id, "TS-7801")
        self.assertIn(training.status, HANDED_IN)
        self.assertEqual(visit.activity_type, "school_visit")
        self.assertTrue(visit.ssa_collection_expected)
        self.assertEqual(visit.salesforce_activity_id, "SVE-7801")
        self.assertIn(visit.status, HANDED_IN)
        self.assertTrue(SsaRecord.objects.filter(source_activity_id=visit.id).exists())
        self.assertFalse(awaits_training(visit))

    def test_edit_names_it_too(self):
        visit = self._converted()
        response = self._client().post(
            f"/my-plan/{visit.id}/edit",
            {
                "reason": "",
                "purpose_type": "in_school_training_ssa",
                "purpose_training_course_id": _a_course_id(),
            },
            headers={"HX-Request": "true"},
        )
        self.assertEqual(response.status_code, 200, response.content)
        self.assertTrue(Activity.objects.filter(paired_school_visit=visit).exists())

    def test_the_edit_drawer_shows_the_training_list(self):
        response = self._client().get(f"/my-plan/{self._converted().id}/edit-drawer")
        self.assertContains(response, "data-awaits-training")
        self.assertContains(response, "awaitsTraining: true")

    def test_a_date_only_edit_still_saves(self):
        from apps.activities.test_activity_editing import _weekday

        visit = self._converted()
        new_day = _weekday(9)
        response = self._client().post(
            f"/my-plan/{visit.id}/edit",
            {
                "reason": "Moved by the school",
                "purpose_type": "in_school_training_ssa",
                "scheduled_date": new_day.isoformat(),
            },
            headers={"HX-Request": "true"},
        )
        self.assertEqual(response.status_code, 200, response.content)
        visit.refresh_from_db()
        self.assertEqual(visit.planned_date, new_day)
        self.assertTrue(awaits_training(visit))


class OnlyTheSsaWasCollected(_Fixture):
    def test_it_completes_as_ssa_support(self):
        visit = self._converted()
        response = self._complete(
            visit,
            purpose_type="ssa_support",
            ssa_collected="yes",
            salesforce_id="SVE-7901",
            **_scores(),
        )
        self.assertEqual(response.status_code, 200, response.content)
        visit.refresh_from_db()
        self.assertEqual(visit.purpose_type, "ssa_support")
        self.assertIn(visit.status, HANDED_IN)
        self.assertFalse(Activity.objects.filter(paired_school_visit=visit).exists())
