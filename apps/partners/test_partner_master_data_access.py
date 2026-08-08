"""§13: a Partner delivers an assignment; it does not own the School.

Assigning work to a Partner must not hand them the School record. The spec
lists what stays out of reach — owner, District, Sub-county, Cluster, School
status, Core status, SSA and the rest of the master data — and these tests hold
each of those endpoints against a real Partner session rather than trusting the
permission table to be read correctly.

The table currently grants the two Partner roles exactly three permissions, so
every case below should already pass. That is the point: this is a regression
guard for the day someone widens a role to fix an unrelated complaint, which is
how `data.export` came to be enforced by one endpoint out of twenty. It fails
loudly at the endpoint, which is where the rule has to hold.
"""

from __future__ import annotations

from django.test import TestCase
from django.urls import reverse

from apps.accounts.models import User
from apps.clusters.models import Cluster
from apps.core.rbac import EdifyRole
from apps.geography.models import District, Region, SubCounty
from apps.partners.models import Partner
from apps.schools.models import School

# Anything that is not a straight-through 2xx means the Partner was stopped.
# The gate is a redirect to sign-in or an access-denied render depending on the
# decorator, and asserting one exact status would pin the test to which of the
# two a given endpoint happens to use rather than to the rule itself.
BLOCKED = {302, 400, 403, 404, 405}


class PartnerCannotEditSchoolMasterDataTest(TestCase):
    def setUp(self):
        self.region = Region.objects.create(name="Partner Access Region")
        self.district = District.objects.create(
            name="Partner Access District", region=self.region
        )
        self.sub_county = SubCounty.objects.create(
            name="Partner Access SubCounty", district=self.district
        )
        self.school = School.objects.create(
            school_id="SCH-PARTNER-ACCESS",
            name="Partner Access Primary",
            region=self.region,
            district=self.district,
            sub_county=self.sub_county,
            school_type="client",
        )
        self.cluster = Cluster.objects.create(
            name="Partner Access Cluster",
            region=self.region,
            district=self.district,
            sub_county=self.sub_county,
            cluster_type="mixed",
            status="active",
        )
        self.partner_user = User.objects.create_user(
            email="officer@partner.test",
            name="Partner Officer",
            roles=[EdifyRole.PARTNER_FIELD_OFFICER.value],
            active_role=EdifyRole.PARTNER_FIELD_OFFICER.value,
            password="pwd",
            is_active=True,
        )
        Partner.objects.create(
            name="Access Test Partner",
            user=self.partner_user,
            active_status=True,
        )
        self.client.force_login(self.partner_user)

    def _forbidden(self, url, method="post", data=None):
        response = getattr(self.client, method)(url, data or {})
        self.assertIn(
            response.status_code,
            BLOCKED,
            f"{method.upper()} {url} answered {response.status_code} for a Partner",
        )
        return response

    def test_partner_cannot_open_or_submit_the_school_edit_drawer(self):
        """Owner, District, Sub-county and master data all live behind this."""
        url = reverse("frontend:school_edit_drawer", args=[self.school.school_id])
        self._forbidden(url, method="get")
        self._forbidden(
            url,
            data={
                "name": "Renamed By Partner",
                "district_id": self.district.id,
                "account_owner_id": "someone-else",
            },
        )
        self.school.refresh_from_db()
        self.assertEqual(self.school.name, "Partner Access Primary")

    def test_partner_cannot_change_school_cluster_membership(self):
        self._forbidden(
            reverse("frontend:bulk_assign_cluster"),
            data={"school_ids": self.school.id, "cluster_id": self.cluster.id},
        )
        self.school.refresh_from_db()
        self.assertIsNone(self.school.cluster_id)

    def test_partner_cannot_change_school_type_or_core_status(self):
        self._forbidden(
            reverse("frontend:school_change_type", args=[self.school.school_id]),
            data={"school_type": "core"},
        )
        self.school.refresh_from_db()
        self.assertEqual(self.school.school_type, "client")

    def test_partner_cannot_delete_a_school(self):
        self._forbidden(reverse("frontend:school_delete", args=[self.school.school_id]))
        self.assertTrue(School.objects.filter(pk=self.school.pk).exists())

    def test_partner_cannot_edit_a_cluster(self):
        self._forbidden(
            reverse("frontend:edit_cluster", args=[self.cluster.id]),
            data={"name": "Renamed By Partner"},
        )
        self.cluster.refresh_from_db()
        self.assertEqual(self.cluster.name, "Partner Access Cluster")

    def test_partner_cannot_create_a_cluster(self):
        before = Cluster.objects.count()
        self._forbidden(
            reverse("frontend:create_cluster"),
            data={
                "name": "Partner Made Cluster",
                "district_id": self.district.id,
                "sub_county_id": self.sub_county.id,
            },
        )
        self.assertEqual(Cluster.objects.count(), before)

    def test_partner_cannot_reach_the_ssa_write_surfaces(self):
        """SSA is the assessment record the whole programme is scored on."""
        for name in ("ssa_manual_entry", "ssa_upload_center"):
            with self.subTest(endpoint=name):
                self._forbidden(reverse(f"frontend:{name}"), method="get")
