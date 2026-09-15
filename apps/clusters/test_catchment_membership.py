"""Cluster catchments and Add / Change Cluster (owner, 2026-09-15).

A school may join one of its owner's clusters when the cluster serves the
school's district: its own district, or a neighbouring district a Country
Director or Admin approved for it, inside the approval's window and within the
same country. Joining never changes the school's geography. A school has one
active cluster; every change closes the old membership in the history.
"""

from __future__ import annotations

from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from apps.accounts.models import StaffProfile, StaffSchoolAssignment
from apps.audit.models import AuditLog
from apps.clusters.catchment import (
    approve_neighbouring_district,
    end_catchment,
    serving_match,
)
from apps.clusters.models import (
    Cluster,
    ClusterServiceDistrict,
    SchoolClusterAssignment,
    SchoolClusterMembership,
)
from apps.clusters.services import set_school_cluster_membership
from apps.core.exceptions import BadRequest, Forbidden
from apps.geography.models import District, Region, SubCounty
from apps.schools.models import School

User = get_user_model()


class CatchmentFixture(TestCase):
    def setUp(self):
        self.region = Region.objects.create(name="Border Region")
        self.home = District.objects.create(name="Home District", region=self.region)
        self.neighbour = District.objects.create(
            name="Neighbour District", region=self.region
        )
        self.far = District.objects.create(name="Far District", region=self.region)
        self.foreign_region = Region.objects.create(
            name="Foreign Region", country="Kenya"
        )
        self.foreign = District.objects.create(
            name="Foreign District", region=self.foreign_region
        )
        self.home_sc = SubCounty.objects.create(name="Home SC", district=self.home)
        self.neighbour_sc = SubCounty.objects.create(
            name="Neighbour SC", district=self.neighbour
        )

        self.cceo = User.objects.create_user(
            email="catch-cceo@edify.test",
            name="Catch Cceo",
            roles=["CCEO"],
            active_role="CCEO",
            password="StrongPassphrase!23",
        )
        self.profile = StaffProfile.objects.create(user=self.cceo, title="CCEO")
        self.cd = User.objects.create_user(
            email="catch-cd@edify.test",
            name="Catch Cd",
            roles=["CountryDirector"],
            active_role="CountryDirector",
            password="StrongPassphrase!23",
        )
        StaffProfile.objects.create(user=self.cd, title="CD")
        self.ia = User.objects.create_user(
            email="catch-ia@edify.test",
            name="Catch Ia",
            roles=["ImpactAssessment"],
            active_role="ImpactAssessment",
            password="StrongPassphrase!23",
        )
        StaffProfile.objects.create(user=self.ia, title="IA")

        self.home_cluster = self._cluster("Home Cluster", self.home)
        self.second_home_cluster = self._cluster("Second Home Cluster", self.home)
        self.border_cluster = self._cluster("Border Cluster", self.neighbour)
        self.far_cluster = self._cluster("Far Cluster", self.far)

        self.school = School.objects.create(
            school_id="BORDER-1",
            name="Border Primary",
            region=self.region,
            district=self.home,
            sub_county=self.home_sc,
            school_type="client",
            account_owner_id=self.profile.id,
        )
        StaffSchoolAssignment.objects.create(
            staff=self.profile, school_id=self.school.id
        )

    def _cluster(self, name, district, **extra):
        return Cluster.objects.create(
            name=name,
            region=district.region,
            district=district,
            cluster_type="mixed",
            status=extra.pop("status", "active"),
            responsible_staff_id=self.profile.id,
            **extra,
        )

    def _approve_border(self, **kwargs):
        return approve_neighbouring_district(
            self.border_cluster.id,
            self.home.id,
            self.cd,
            reason=kwargs.pop("reason", "Serves the border villages on the river."),
            **kwargs,
        )


class CatchmentRuleTests(CatchmentFixture):
    def test_every_cluster_serves_its_own_district(self):
        rows = ClusterServiceDistrict.objects.filter(
            cluster=self.home_cluster, active=True
        )
        self.assertEqual(
            list(rows.values_list("district_id", "relationship_type")),
            [(self.home.id, "primary")],
        )

    def test_same_district_cluster_is_accepted(self):
        set_school_cluster_membership(self.school, self.home_cluster, self.cceo.id)
        self.school.refresh_from_db()
        self.assertEqual(self.school.cluster_id, self.home_cluster.id)

    def test_approved_neighbouring_district_cluster_is_accepted(self):
        self._approve_border()
        set_school_cluster_membership(
            self.school,
            self.border_cluster,
            self.cceo.id,
            reason="Children cross the river to the cluster centre.",
        )
        self.school.refresh_from_db()
        self.assertEqual(self.school.cluster_id, self.border_cluster.id)
        # Geography is untouched.
        self.assertEqual(self.school.district_id, self.home.id)
        self.assertEqual(self.school.sub_county_id, self.home_sc.id)
        membership = SchoolClusterMembership.objects.get(
            school=self.school, ended_at__isnull=True
        )
        self.assertTrue(membership.is_cross_district)
        self.assertEqual(membership.relationship_type, "neighbouring")
        # A cross-district join declares no coverage in another district.
        self.assertFalse(
            self.border_cluster.covered_sub_counties.filter(
                sub_county=self.home_sc
            ).exists()
        )

    def test_unapproved_district_is_rejected(self):
        with self.assertRaises(BadRequest) as ctx:
            set_school_cluster_membership(self.school, self.far_cluster, self.cceo.id)
        self.assertIn("does not serve Home District", str(ctx.exception))
        self.school.refresh_from_db()
        self.assertIsNone(self.school.cluster_id)

    def test_a_cluster_never_serves_another_country(self):
        with self.assertRaises(BadRequest):
            approve_neighbouring_district(
                self.border_cluster.id,
                self.foreign.id,
                self.cd,
                reason="Across the national border, which is never allowed.",
            )
        foreign_cluster = self._cluster("Foreign Cluster", self.foreign)
        with self.assertRaises(BadRequest):
            set_school_cluster_membership(self.school, foreign_cluster, self.cceo.id)

    def test_an_ended_or_future_or_expired_catchment_is_rejected(self):
        row = self._approve_border()
        end_catchment(row.id, self.cd, reason="The river bridge reopened.")
        self.assertIsNone(serving_match(self.border_cluster, self.home.id))
        with self.assertRaises(BadRequest):
            set_school_cluster_membership(
                self.school, self.border_cluster, self.cceo.id
            )

        today = timezone.localdate()
        future = self._approve_border(effective_from=today + timedelta(days=5))
        self.assertIsNone(serving_match(self.border_cluster, self.home.id))
        future.effective_from = today - timedelta(days=30)
        future.effective_to = today - timedelta(days=1)
        future.save()
        self.assertIsNone(serving_match(self.border_cluster, self.home.id))

    def test_a_closed_cluster_is_rejected(self):
        self.home_cluster.status = "inactive"
        self.home_cluster.save()
        with self.assertRaises(BadRequest):
            set_school_cluster_membership(self.school, self.home_cluster, self.cceo.id)

    def test_one_active_cluster_and_history_preserved_on_change(self):
        set_school_cluster_membership(self.school, self.home_cluster, self.cceo.id)
        set_school_cluster_membership(
            self.school,
            self.second_home_cluster,
            self.cceo.id,
            reason="Closer cluster centre.",
        )
        rows = SchoolClusterMembership.objects.filter(school=self.school).order_by(
            "started_at"
        )
        self.assertEqual(
            [r.cluster_id for r in rows],
            [self.home_cluster.id, self.second_home_cluster.id],
        )
        self.assertIsNotNone(rows[0].ended_at)
        self.assertEqual(rows[0].end_reason, "Closer cluster centre.")
        self.assertEqual(
            SchoolClusterMembership.objects.filter(
                school=self.school, ended_at__isnull=True
            ).count(),
            1,
        )
        self.assertEqual(
            list(
                SchoolClusterAssignment.objects.filter(school=self.school).values_list(
                    "cluster_id", flat=True
                )
            ),
            [self.second_home_cluster.id],
        )

    def test_counts_follow_the_membership(self):
        from apps.clusters.services import active_school_count

        set_school_cluster_membership(self.school, self.home_cluster, self.cceo.id)
        self.assertEqual(active_school_count(self.home_cluster.id), 1)
        set_school_cluster_membership(
            self.school, self.second_home_cluster, self.cceo.id, reason="Move."
        )
        self.assertEqual(active_school_count(self.home_cluster.id), 0)
        self.assertEqual(active_school_count(self.second_home_cluster.id), 1)

    def test_changes_are_audited_with_previous_new_and_reason(self):
        self._approve_border()
        set_school_cluster_membership(self.school, self.home_cluster, self.cceo.id)
        set_school_cluster_membership(
            self.school,
            self.border_cluster,
            self.cceo.id,
            reason="Border village.",
            actor_role="CCEO",
        )
        row = (
            AuditLog.objects.filter(
                action="cluster.membership_changed", subject_id=self.school.id
            )
            .order_by("-created_at")
            .first()
        )
        self.assertEqual(row.reason, "Border village.")
        self.assertEqual(row.actor_role, "CCEO")
        self.assertEqual(row.payload["previous"]["clusterId"], self.home_cluster.id)
        self.assertEqual(row.payload["new"]["clusterId"], self.border_cluster.id)
        self.assertTrue(row.payload["new"]["crossDistrict"])
        self.assertTrue(
            AuditLog.objects.filter(
                action="cluster.catchment_approved", subject_id=self.border_cluster.id
            ).exists()
        )

    def test_only_cd_and_admin_manage_catchments(self):
        for principal in (self.cceo, self.ia):
            with self.subTest(role=principal.active_role):
                with self.assertRaises(Forbidden):
                    approve_neighbouring_district(
                        self.border_cluster.id,
                        self.home.id,
                        principal,
                        reason="Trying without the authority to approve.",
                    )

    def test_a_geography_edit_that_rederives_the_cluster_is_historied(self):
        self.home_cluster.sub_county = self.home_sc
        self.home_cluster.save()
        self.school.sub_county = None
        self.school.save()
        self.school.sub_county = self.home_sc
        self.school.save()
        self.school.refresh_from_db()
        self.assertEqual(self.school.cluster_id, self.home_cluster.id)
        self.assertTrue(
            SchoolClusterMembership.objects.filter(
                school=self.school,
                cluster=self.home_cluster,
                ended_at__isnull=True,
                started_by="system_reassign",
            ).exists()
        )


class AddToClusterDrawerTests(CatchmentFixture):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.cceo)
        self.url = f"/schools/{self.school.id}/add-to-cluster"

    def test_the_drawer_lists_the_owner_clusters_and_marks_the_catchment(self):
        self._approve_border()
        response = self.client.get(self.url, HTTP_HX_REQUEST="true")
        self.assertContains(response, "Add to Cluster")
        by_id = {c.id: c for c in response.context["owner_clusters"]}
        self.assertTrue(by_id[self.home_cluster.id].serves_school)
        self.assertTrue(by_id[self.border_cluster.id].is_cross_district)
        self.assertFalse(by_id[self.far_cluster.id].serves_school)
        self.assertContains(response, "Cross-District Cluster")

    def test_a_cross_district_join_needs_a_reason_then_saves(self):
        self._approve_border()
        refused = self.client.post(
            self.url,
            {
                "cluster_action_type": "existing",
                "existing_cluster_id": self.border_cluster.id,
            },
            HTTP_HX_REQUEST="true",
        )
        self.assertContains(refused, "across the district border")
        saved = self.client.post(
            self.url,
            {
                "cluster_action_type": "existing",
                "existing_cluster_id": self.border_cluster.id,
                "reason": "Border village on the river.",
            },
            HTTP_HX_REQUEST="true",
        )
        self.assertContains(saved, "added to Border Cluster")
        self.assertIn("schools-updated", saved["HX-Trigger"])
        self.school.refresh_from_db()
        self.assertEqual(self.school.cluster_id, self.border_cluster.id)
        self.assertEqual(self.school.district_id, self.home.id)

    def test_a_crafted_post_for_an_unserved_cluster_is_refused(self):
        response = self.client.post(
            self.url,
            {
                "cluster_action_type": "existing",
                "existing_cluster_id": self.far_cluster.id,
                "reason": "Should never be allowed.",
            },
            HTTP_HX_REQUEST="true",
        )
        self.assertContains(response, "does not serve Home District")
        self.school.refresh_from_db()
        self.assertIsNone(self.school.cluster_id)

    def test_another_staff_members_cluster_is_never_offered(self):
        other = User.objects.create_user(
            email="catch-other@edify.test",
            name="Other",
            roles=["CCEO"],
            active_role="CCEO",
            password="StrongPassphrase!23",
        )
        other_profile = StaffProfile.objects.create(user=other, title="CCEO")
        theirs = Cluster.objects.create(
            name="Their Cluster",
            region=self.region,
            district=self.home,
            status="active",
            responsible_staff_id=other_profile.id,
        )
        response = self.client.get(self.url, HTTP_HX_REQUEST="true")
        self.assertNotIn(theirs.id, [c.id for c in response.context["owner_clusters"]])

    def test_full_page_fallback_redirects_to_the_directory(self):
        response = self.client.post(
            self.url,
            {
                "cluster_action_type": "existing",
                "existing_cluster_id": self.home_cluster.id,
            },
        )
        self.assertRedirects(response, "/schools", fetch_redirect_response=False)
        self.school.refresh_from_db()
        self.assertEqual(self.school.cluster_id, self.home_cluster.id)

    def test_the_honest_empty_state(self):
        Cluster.objects.filter(responsible_staff_id=self.profile.id).exclude(
            id=self.far_cluster.id
        ).update(status="inactive")
        response = self.client.get(self.url, HTTP_HX_REQUEST="true")
        self.assertContains(
            response,
            "No eligible clusters serve this school's district or approved "
            "neighbouring districts.",
        )

    def test_a_supervisor_is_told_before_saving(self):
        pl = User.objects.create_user(
            email="catch-pl@edify.test",
            name="Catch Pl",
            roles=["Program Lead"],
            active_role="Program Lead",
            password="StrongPassphrase!23",
        )
        StaffProfile.objects.create(user=pl, title="PL")
        self.client.force_login(pl)
        response = self.client.get(self.url, HTTP_HX_REQUEST="true")
        self.assertIn(response.status_code, (200, 403, 404))
        self.assertNotContains(
            response, "Add to Cluster", status_code=response.status_code
        )

    def test_the_cluster_profile_manages_the_catchment_for_the_cd(self):
        row = self._approve_border()
        self.client.force_login(self.cd)
        page = self.client.get(f"/clusters/{self.border_cluster.id}")
        self.assertContains(page, "Districts served")
        self.assertContains(page, "Approve Neighbouring District")
        self.assertContains(page, "Home District")
        drawer = self.client.get(
            f"/clusters/{self.border_cluster.id}/catchment-drawer",
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(drawer.status_code, 200)
        self.assertNotIn(self.foreign.id, [d.id for d in drawer.context["districts"]])
        ended = self.client.post(
            f"/clusters/{self.border_cluster.id}/catchment/{row.id}/end",
            {"reason": "No longer needed."},
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(ended.status_code, 200)
        row.refresh_from_db()
        self.assertFalse(row.active)

    def test_a_cceo_cannot_open_the_catchment_drawer(self):
        response = self.client.get(
            f"/clusters/{self.border_cluster.id}/catchment-drawer",
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(response.status_code, 403)
