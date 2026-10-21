"""Correcting a planned visit's purpose in place (owner, 2026-10-19).

"The user had intended to schedule ssa support visit. he should be able to
edit the activity to what he intended." A visit planned as a Training Follow
Up, where no training has been completed for it to follow up, could never be
completed: completion asks for the training it answered. The planner changes
the purpose on the visit itself, from its Edit drawer, and keeps the one
Activity ID, its school, its day, its owner and its notes.

Pinned here:

  1. A client school's Training Follow Up becomes SSA Support on the same
     activity: its workflow, its catalogue entry and price follow, it now
     collects the SSA, it no longer names a training, the change is in the
     audit trail, and it completes with its Salesforce ID.
  2. A Core package visit changes between the package's two visit purposes
     and keeps its slot; it does not leave the package for an outreach
     purpose.
  3. A change the rules refuse leaves the visit as it was.
  4. Work already carried out, and someone else's work, is not changed.
  5. The Edit drawer offers the purposes and saves the one chosen.
"""

from __future__ import annotations

import datetime

from django.test import Client
from django.utils import timezone

from apps.activities import editing, services
from apps.activities.models import Activity
from apps.activities.test_activity_editing import EditingFixture
from apps.audit.models import AuditLog
from apps.core.exceptions import BadRequest, Forbidden
from apps.core.fy import get_operational_fy
from apps.schools.models import School


class _Fixture(EditingFixture):
    def _follow_up(self, school=None) -> Activity:
        """A Training Follow Up planned with no training to follow up."""
        visit = self._visit(school)
        Activity.objects.filter(id=visit.id).update(
            activity_type="training_follow_up_visit",
            purpose_type="training_follow_up",
            activity_purpose_text="Training Follow Up for Profile Cluster cluster schools",
        )
        visit.refresh_from_db()
        return visit

    def _change(self, activity, purpose, user=None, **extra):
        return editing.edit(
            activity.id,
            {"purposeType": purpose, "reason": "Planned the wrong purpose", **extra},
            user or self.cceo,
        )


class AFollowUpBecomesSsaSupport(_Fixture):
    def test_the_same_visit_changes_purpose(self):
        visit = self._follow_up()
        before = Activity.objects.count()

        result = self._change(visit, "ssa_support")

        self.assertEqual(result["id"], visit.id)
        self.assertEqual(Activity.objects.count(), before)
        visit.refresh_from_db()
        self.assertEqual(visit.purpose_type, "ssa_support")
        self.assertEqual(visit.activity_type, "school_visit_ssa_collection")
        self.assertTrue(visit.ssa_collection_expected)
        self.assertIsNone(visit.follow_up_of_activity_id)
        self.assertEqual(services.sf_kind_for_activity(visit), "visit")
        self.assertFalse(visit.activity_purpose_text.startswith("Training Follow Up"))
        self.assertEqual(visit.status, "scheduled")
        self.assertEqual(visit.school_id, self.fresh.id)
        self.assertEqual(visit.responsible_staff_id, str(self.cceo_staff.id))

    def test_the_change_is_in_the_audit_trail(self):
        visit = self._follow_up()
        self._change(visit, "ssa_support")
        entry = AuditLog.objects.filter(
            action="activity.purpose_changed", subject_id=visit.id
        ).get()
        self.assertEqual(entry.payload["from"]["purposeType"], "training_follow_up")
        self.assertEqual(entry.payload["to"]["purposeType"], "ssa_support")
        self.assertEqual(entry.payload["from"]["purpose"], "Training Follow Up")
        self.assertEqual(entry.payload["to"]["purpose"], "SSA Support")
        self.assertEqual(entry.reason, "Planned the wrong purpose")
        self.assertEqual(entry.actor_id, str(self.cceo.id))

    def test_it_completes_with_its_salesforce_id(self):
        visit = self._follow_up()
        services.start_completion(visit.id, principal=self.cceo)
        with self.assertRaises(BadRequest):
            # As planned it asks for a training nobody has delivered.
            services.complete(visit.id, {"salesforceId": "SVE-9101"}, self.cceo)

        self._change(visit, "ssa_support")
        services.complete(
            visit.id,
            {"salesforceId": "SVE-9101", "ssaNotCollectedReason": "Head away"},
            self.cceo,
        )
        visit.refresh_from_db()
        self.assertIn(visit.status, ("submitted_to_pl", "awaiting_ia_verification"))
        self.assertEqual(visit.salesforce_activity_id, "SVE-9101")

    def test_it_is_still_priced(self):
        visit = self._follow_up()
        with self.captureOnCommitCallbacks(execute=True):
            self._change(visit, "ssa_support")
        visit.refresh_from_db()
        self.assertTrue(visit.schedule_cost_lines.exists())

    def test_naming_the_purpose_it_already_has_changes_nothing(self):
        visit = self._follow_up()
        self._change(visit, "training_follow_up")
        self.assertFalse(
            AuditLog.objects.filter(
                action="activity.purpose_changed", subject_id=visit.id
            ).exists()
        )


class ACorePackageVisit(_Fixture):
    def setUp(self):
        super().setUp()
        self.core = School.objects.create(
            school_id="PROFILE-CORE",
            name="Profile Core",
            region=self.region,
            district=self.district,
            school_type="core",
            account_owner_id=self.cceo_staff.id,
        )
        day = timezone.localdate() + datetime.timedelta(days=8)
        self.slot_visit = Activity.objects.create(
            activity_type="core_visit",
            purpose_type="training_follow_up",
            status="scheduled",
            fy=get_operational_fy(day),
            planned_date=day,
            school=self.core,
            responsible_staff_id=str(self.cceo_staff.id),
            activity_purpose_text="Training Follow Up for Profile Cluster cluster schools",
        )

    def test_it_becomes_ssa_support_and_keeps_its_slot(self):
        self._change(self.slot_visit, "ssa_support")
        self.slot_visit.refresh_from_db()
        self.assertEqual(self.slot_visit.activity_type, "core_visit")
        self.assertEqual(self.slot_visit.purpose_type, "ssa_support")
        self.assertTrue(self.slot_visit.ssa_collection_expected)

    def test_it_does_not_leave_the_package_for_an_outreach_purpose(self):
        with self.assertRaises(BadRequest):
            self._change(self.slot_visit, "donor_visit")
        self.slot_visit.refresh_from_db()
        self.assertEqual(self.slot_visit.purpose_type, "training_follow_up")


class RefusedChangesLeaveTheVisitAsItWas(_Fixture):
    def test_an_unknown_purpose(self):
        visit = self._follow_up()
        with self.assertRaises(BadRequest):
            self._change(visit, "not_a_purpose")
        visit.refresh_from_db()
        self.assertEqual(visit.purpose_type, "training_follow_up")

    def test_in_school_training_without_the_training_named(self):
        # It names the training delivered (owner, 2026-10-20), which is
        # created beside the visit (test_completion_purpose).
        visit = self._follow_up()
        with self.assertRaises(BadRequest):
            self._change(visit, "in_school_training")
        visit.refresh_from_db()
        self.assertEqual(visit.purpose_type, "training_follow_up")
        self.assertFalse(Activity.objects.filter(paired_school_visit=visit).exists())

    def test_work_already_carried_out(self):
        visit = self._follow_up()
        Activity.objects.filter(id=visit.id).update(status="submitted_to_pl")
        with self.assertRaises(BadRequest):
            self._change(visit, "ssa_support")
        visit.refresh_from_db()
        self.assertEqual(visit.purpose_type, "training_follow_up")

    def test_someone_else_s_work(self):
        visit = self._follow_up()
        with self.assertRaises((Forbidden, BadRequest)):
            self._change(visit, "ssa_support", user=self.pl)
        visit.refresh_from_db()
        self.assertEqual(visit.purpose_type, "training_follow_up")


class TheEditDrawer(_Fixture):
    def _client(self):
        client = Client()
        client.force_login(self.cceo)
        return client

    def test_it_offers_the_purposes(self):
        visit = self._follow_up()
        response = self._client().get(f"/my-plan/{visit.id}/edit-drawer")
        self.assertContains(response, 'name="purpose_type"')
        self.assertContains(response, 'value="ssa_support"')
        self.assertContains(response, "Training Follow Up")

    def test_it_saves_the_purpose_chosen(self):
        visit = self._follow_up()
        response = self._client().post(
            f"/my-plan/{visit.id}/edit",
            {"purpose_type": "ssa_support", "reason": "Meant SSA Support"},
            headers={"HX-Request": "true"},
        )
        self.assertEqual(response.status_code, 200, response.content)
        visit.refresh_from_db()
        self.assertEqual(visit.purpose_type, "ssa_support")
