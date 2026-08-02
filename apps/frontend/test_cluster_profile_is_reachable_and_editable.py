"""A cluster profile you cannot reach, and cannot edit once you do.

Both halves existed and neither was wired up. `/clusters/<id>` rendered a full
profile, and `/clusters/<id>/edit-drawer` rendered a working edit form — but
the directory printed the cluster name as plain text, and the profile offered
no way to open the drawer. The only route to either was typing the URL.

A school gets both affordances: its name is a link, and its profile carries an
Edit Details button. A cluster is the same kind of record — it has a name, a
type, boundaries and a responsible person, and all of them change — so it
should behave the same way.

The permission detail is the part worth holding: the button is gated on the
same check the drawer enforces, not on a role string. A template that guesses
can offer a control the endpoint refuses, or hide one the user is entitled to,
and both are worse than no button.
"""

from __future__ import annotations

from django.contrib.auth import get_user_model
from django.test import TestCase

from apps.accounts.models import StaffProfile
from apps.clusters.models import Cluster
from apps.geography.models import District, Region, SubCounty

User = get_user_model()


class ClusterProfileReachabilityTest(TestCase):
    def setUp(self):
        self.region = Region.objects.create(name="CP Region")
        self.district = District.objects.create(name="CP District", region=self.region)
        self.sub_county = SubCounty.objects.create(
            name="CP Sub County", district=self.district
        )
        self.cluster = Cluster.objects.create(
            name="CP Cluster",
            region=self.region,
            district=self.district,
            sub_county=self.sub_county,
            cluster_type="mixed",
            status="active",
        )
        self.user = User.objects.create(
            id="cp-admin",
            email="cp-admin@edify.org",
            name="CP Admin",
            roles=["Admin"],
            active_role="Admin",
            is_active=True,
        )
        StaffProfile.objects.create(id="cp-sp", user=self.user, title="Admin")
        self.client.force_login(self.user)

    # ── reachable ────────────────────────────────────────────────────────────

    def test_the_directory_links_the_cluster_name_to_its_profile(self):
        response = self.client.get("/clusters")
        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            f'href="/clusters/{self.cluster.id}"',
            msg_prefix=(
                "the profile exists; without a link from the name the only way "
                "to reach it is to type the URL"
            ),
        )

    def test_the_profile_renders(self):
        response = self.client.get(f"/clusters/{self.cluster.id}")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.cluster.name)

    # ── editable ─────────────────────────────────────────────────────────────

    def test_the_profile_offers_an_edit_control(self):
        response = self.client.get(f"/clusters/{self.cluster.id}")
        self.assertContains(response, f"/clusters/{self.cluster.id}/edit-drawer")
        self.assertContains(response, "Edit Details")

    def test_the_edit_drawer_actually_opens(self):
        """A button pointing at a broken endpoint is worse than no button."""
        response = self.client.get(f"/clusters/{self.cluster.id}/edit-drawer")
        self.assertEqual(response.status_code, 200)

    def test_the_control_and_the_endpoint_agree_on_permission(self):
        """The button is gated on the same check the drawer enforces. If the
        two ever diverge, one of them is lying to the user."""
        from apps.core.permissions import RolePermissionService

        page_response = self.client.get(f"/clusters/{self.cluster.id}")
        offered = "Edit Details" in page_response.content.decode()
        allowed = RolePermissionService.can_view_page(self.user, "planning")
        self.assertEqual(
            offered,
            allowed,
            "the control must appear exactly when the drawer would open",
        )

    def test_the_profile_states_its_district_and_sub_county(self):
        """cluster here is the serialized detail dict, whose keys are camelCase
        — subCounty, not sub_county. Getting that wrong renders an empty string
        silently rather than raising, so it is asserted rather than assumed."""
        response = self.client.get(f"/clusters/{self.cluster.id}")
        self.assertContains(response, self.district.name)
        self.assertContains(response, self.sub_county.name)
