"""Deleting a cluster releases its schools; a cluster that hosted work stays.

Owner, 2026-09-11: "The staff should be able to delete cluster and the schools
added to the deleted clusters can just get unclustered ready to be added to a
new cluster. If the clusters have had a meeting or training, the staff should
not be able to delete it."
"""

from __future__ import annotations

from datetime import date

from django.contrib.auth import get_user_model
from django.test import TestCase

from apps.accounts.models import StaffProfile
from apps.activities.models import Activity
from apps.clusters.models import Cluster
from apps.clusters.services import (
    cluster_delete_block,
    delete_cluster,
    set_school_cluster_membership,
)
from apps.core.exceptions import BadRequest, Forbidden
from apps.geography.models import District, Region, SubCounty
from apps.schools.models import School

User = get_user_model()


def _staff(uid, role, name):
    user = User.objects.create(
        id=uid, email=f"{uid}@edify.org", name=name, roles=[role],
        active_role=role, is_active=True,
    )
    return user, StaffProfile.objects.create(id=f"{uid}-sp", user=user, title=role)


class ClusterDeletionTest(TestCase):
    def setUp(self):
        self.region = Region.objects.create(name="Del Region")
        self.district = District.objects.create(name="Del District", region=self.region)
        self.sub_county = SubCounty.objects.create(name="Del SC", district=self.district)
        self.owner, self.owner_sp = _staff("del-cceo", "CCEO", "Del Owner")
        self.other, self.other_sp = _staff("del-other", "CCEO", "Del Other")
        self.cluster = Cluster.objects.create(
            name="Del Cluster", region=self.region, district=self.district,
            sub_county=self.sub_county, cluster_type="mixed", status="active",
            responsible_staff_id=self.owner_sp.id,
        )
        self.schools = [
            School.objects.create(
                school_id=f"DEL-{i}", name=f"Del School {i}", region=self.region,
                district=self.district, sub_county=self.sub_county,
                account_owner_id=self.owner_sp.id,
            )
            for i in range(2)
        ]
        for school in self.schools:
            set_school_cluster_membership(school, self.cluster, assigned_by="test")

    def _work(self, status, kind="cluster_meeting"):
        return Activity.objects.create(
            activity_type=kind, status=status, cluster=self.cluster,
            planned_date=date(2026, 9, 20), fy="2026",
        )

    def test_a_fresh_cluster_is_deleted_and_its_schools_released(self):
        result = delete_cluster(self.cluster.id, self.owner)
        self.assertEqual(result["schoolsReleased"], 2)
        self.assertIsNotNone(Cluster.all_objects.get(id=self.cluster.id).deleted_at)
        self.assertFalse(Cluster.objects.filter(id=self.cluster.id).exists())
        for school in self.schools:
            school.refresh_from_db()
            self.assertIsNone(school.cluster_id)
            self.assertEqual(school.cluster_status, "unclustered")

    def test_a_cluster_that_held_a_meeting_is_kept(self):
        self._work("completed")
        reason = cluster_delete_block(self.cluster)
        self.assertIn("has held 1 meeting", reason)
        with self.assertRaises(BadRequest):
            delete_cluster(self.cluster.id, self.owner)
        self.assertTrue(Cluster.objects.filter(id=self.cluster.id).exists())
        self.schools[0].refresh_from_db()
        self.assertEqual(self.schools[0].cluster_id, self.cluster.id)

    def test_a_verified_training_counts_as_held_work_too(self):
        self._work("ia_verified", kind="cluster_training")
        self.assertIn("has held", cluster_delete_block(self.cluster))

    def test_a_scheduled_meeting_asks_the_planner_to_move_it_first(self):
        self._work("scheduled")
        reason = cluster_delete_block(self.cluster)
        self.assertIn("scheduled meeting or training", reason)
        self.assertIn("Cancel or move it", reason)
        with self.assertRaises(BadRequest):
            delete_cluster(self.cluster.id, self.owner)

    def test_a_cancelled_meeting_does_not_hold_the_cluster(self):
        self._work("cancelled")
        self.assertIsNone(cluster_delete_block(self.cluster))
        delete_cluster(self.cluster.id, self.owner)
        self.assertFalse(Cluster.objects.filter(id=self.cluster.id).exists())

    def test_another_staff_members_cluster_is_refused(self):
        with self.assertRaises(Forbidden):
            delete_cluster(self.cluster.id, self.other)
        self.assertTrue(Cluster.objects.filter(id=self.cluster.id).exists())


class ClusterDeletionSurfaceTest(TestCase):
    def setUp(self):
        self.region = Region.objects.create(name="DelS Region")
        self.district = District.objects.create(name="DelS District", region=self.region)
        self.sub_county = SubCounty.objects.create(name="DelS SC", district=self.district)
        self.user, self.sp = _staff("dels-admin", "Admin", "DelS Admin")
        self.cluster = Cluster.objects.create(
            name="DelS Cluster", region=self.region, district=self.district,
            sub_county=self.sub_county, cluster_type="mixed", status="active",
        )
        self.client.force_login(self.user)

    def test_the_profile_offers_delete_on_a_fresh_cluster(self):
        response = self.client.get(f"/clusters/{self.cluster.id}")
        self.assertContains(response, f'hx-post="/clusters/{self.cluster.id}/delete"')
        self.assertNotContains(response, "data-cluster-delete-blocked")

    def test_the_profile_explains_why_a_working_cluster_cannot_be_deleted(self):
        Activity.objects.create(
            activity_type="cluster_training", status="completed", cluster=self.cluster,
            planned_date=date(2026, 9, 20), fy="2026",
        )
        response = self.client.get(f"/clusters/{self.cluster.id}")
        self.assertContains(response, "data-cluster-delete-blocked")
        self.assertContains(response, "has held 1 meeting")
        self.assertNotContains(response, f'hx-post="/clusters/{self.cluster.id}/delete"')

    def test_a_press_deletes_and_sends_the_browser_to_the_directory(self):
        response = self.client.post(
            f"/clusters/{self.cluster.id}/delete", HTTP_HX_REQUEST="true"
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["HX-Redirect"], "/clusters")
        self.assertFalse(Cluster.objects.filter(id=self.cluster.id).exists())

    def test_a_refused_press_shows_the_reason_in_the_page(self):
        Activity.objects.create(
            activity_type="cluster_meeting", status="completed", cluster=self.cluster,
            planned_date=date(2026, 9, 20), fy="2026",
        )
        response = self.client.post(
            f"/clusters/{self.cluster.id}/delete", HTTP_HX_REQUEST="true"
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("has held 1 meeting", response.content.decode())
        self.assertTrue(Cluster.objects.filter(id=self.cluster.id).exists())

    def test_get_is_not_a_delete(self):
        self.assertEqual(self.client.get(f"/clusters/{self.cluster.id}/delete").status_code, 405)
