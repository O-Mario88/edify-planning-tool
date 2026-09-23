"""A partner works in more than one region, and the form can say so.

Owner, 2026-09-23:

  "Can you make sure that partner can be assigned more than one region. Most
  of the partners operate in more than one region."

The single `region_name` dropdown could hold one answer. These tests cover the
tick-list that replaced it: what the drawers offer, what a save stores, that the
single column every existing reader depends on still says something true, and
that the profile shows every region rather than the first.
"""

from __future__ import annotations

import re

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings

from apps.audit.models import AuditLog
from apps.core.rbac import EdifyRole
from apps.geography.models import Region
from apps.partners.models import Partner
from apps.partners.services import onboard, region_list, update

User = get_user_model()
PASSWORD = "StrongPassphrase!23"

_REGION_BOX = re.compile(
    r'<input type="checkbox"\s+name="region_names"\s+value="([^"]+)"\s*(checked)?'
)


def _region_boxes(response) -> dict[str, bool]:
    """Each region tick box the drawer drew, and whether it is ticked."""
    return {
        match.group(1): bool(match.group(2))
        for match in _REGION_BOX.finditer(response.content.decode())
    }


def _user(email: str, role: str) -> User:
    return User.objects.create_user(
        email=email,
        name=email.split("@")[0].title(),
        roles=[role],
        active_role=role,
        password=PASSWORD,
    )


class WhatAPayloadNamesTest(TestCase):
    def test_a_list_is_kept_in_order_trimmed_and_once(self):
        self.assertEqual(
            region_list({"regionNames": [" Northern ", "Eastern", "northern", ""]}),
            ["Northern", "Eastern"],
        )

    def test_the_single_value_older_callers_send_becomes_a_one_item_list(self):
        self.assertEqual(region_list({"regionName": "Central"}), ["Central"])
        self.assertEqual(region_list({"region_name": "Central"}), ["Central"])
        self.assertEqual(region_list({"regionName": ""}), [])

    def test_not_mentioning_regions_is_not_the_same_as_clearing_them(self):
        self.assertIsNone(region_list({"name": "Anything"}))
        self.assertEqual(region_list({"regionNames": []}), [])


class WhatASavedPartnerReadsTest(TestCase):
    def test_a_partner_reads_back_every_region(self):
        partner = Partner.objects.create(
            name="Many Regions Ltd",
            region_name="Northern",
            region_names=["Northern", "Eastern"],
        )
        self.assertEqual(partner.regions, ["Northern", "Eastern"])
        self.assertEqual(partner.region_label, "Northern, Eastern")

    def test_a_partner_saved_before_the_tick_list_still_reads_its_region(self):
        partner = Partner.objects.create(name="One Region Ltd", region_name="Central")
        self.assertEqual(partner.regions, ["Central"])
        self.assertEqual(partner.region_label, "Central")

    def test_a_partner_with_no_region_reads_as_none(self):
        partner = Partner.objects.create(name="No Region Ltd")
        self.assertEqual(partner.regions, [])
        self.assertEqual(partner.region_label, "")

    def test_the_migration_carries_the_single_region_into_the_list(self):
        import importlib

        from django.apps import apps

        migration = importlib.import_module(
            "apps.partners.migrations.0025_partner_region_names"
        )
        legacy = Partner.objects.create(name="Legacy Ltd", region_name="Western")
        blank = Partner.objects.create(name="Blank Ltd")
        already = Partner.objects.create(
            name="Already Ltd",
            region_name="Central",
            region_names=["Central", "Eastern"],
        )
        migration.carry_the_single_region_into_the_list(apps, None)
        legacy.refresh_from_db()
        blank.refresh_from_db()
        already.refresh_from_db()
        self.assertEqual(legacy.region_names, ["Western"])
        self.assertEqual(blank.region_names, [])
        self.assertEqual(already.region_names, ["Central", "Eastern"])


class ServiceTest(TestCase):
    def setUp(self):
        self.cd = _user("regions-cd@edify.test", EdifyRole.COUNTRY_DIRECTOR.value)

    def test_onboarding_stores_every_region_and_the_first_in_the_single_column(self):
        created = onboard(
            {"name": "Across The North", "regionNames": ["Northern", "Eastern"]},
            self.cd,
        )
        partner = Partner.objects.get(id=created["id"])
        self.assertEqual(partner.region_names, ["Northern", "Eastern"])
        self.assertEqual(partner.region_name, "Northern")
        self.assertEqual(created["regionNames"], ["Northern", "Eastern"])
        self.assertEqual(created["regionName"], "Northern")
        row = AuditLog.objects.get(action="partner.created", subject_id=partner.id)
        self.assertEqual(row.payload["new"]["regions"], ["Northern", "Eastern"])

    def test_onboarding_with_the_old_single_region_still_records_it(self):
        created = onboard({"name": "Old Caller", "regionName": "Central"}, self.cd)
        partner = Partner.objects.get(id=created["id"])
        self.assertEqual(partner.region_names, ["Central"])
        self.assertEqual(partner.region_name, "Central")

    def test_an_update_that_does_not_mention_regions_leaves_them_alone(self):
        partner = Partner.objects.create(
            name="Keep Mine",
            region_name="Northern",
            region_names=["Northern", "Eastern"],
        )
        update(partner.id, {"phone": "0700 000 000"}, self.cd)
        partner.refresh_from_db()
        self.assertEqual(partner.region_names, ["Northern", "Eastern"])
        self.assertEqual(partner.region_name, "Northern")

    def test_an_update_replaces_the_regions_and_the_first_follows(self):
        partner = Partner.objects.create(
            name="Moving", region_name="Northern", region_names=["Northern"]
        )
        update(partner.id, {"regionNames": ["Western", "Central"]}, self.cd)
        partner.refresh_from_db()
        self.assertEqual(partner.region_names, ["Western", "Central"])
        self.assertEqual(partner.region_name, "Western")
        row = AuditLog.objects.get(action="partner.updated", subject_id=partner.id)
        self.assertEqual(row.payload["previous"]["regionNames"], ["Northern"])
        self.assertEqual(row.payload["new"]["regionNames"], ["Western", "Central"])

    def test_clearing_every_region_clears_both_columns(self):
        partner = Partner.objects.create(
            name="Clearing",
            region_name="Northern",
            region_names=["Northern", "Eastern"],
        )
        update(partner.id, {"regionNames": []}, self.cd)
        partner.refresh_from_db()
        self.assertEqual(partner.region_names, [])
        self.assertIsNone(partner.region_name)


@override_settings(ALLOWED_HOSTS=["testserver", "localhost"])
class DrawerTest(TestCase):
    def setUp(self):
        for name in ("Central", "Eastern", "Northern", "Western"):
            Region.objects.create(name=name)
        self.cd = _user(
            "regions-drawer-cd@edify.test", EdifyRole.COUNTRY_DIRECTOR.value
        )
        self.client.force_login(self.cd)

    def test_the_add_drawer_offers_every_region_as_a_tick_box(self):
        response = self.client.get("/partners/create")
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'name="region_name"')
        self.assertEqual(
            _region_boxes(response),
            {"Central": False, "Eastern": False, "Northern": False, "Western": False},
        )

    def test_adding_an_organisation_with_three_regions_keeps_all_three(self):
        response = self.client.post(
            "/partners/create",
            {
                "name": "Three Regions Org",
                "region_names": ["Northern", "Eastern", "Western"],
            },
        )
        self.assertEqual(response.status_code, 302)
        partner = Partner.objects.get(name="Three Regions Org")
        self.assertEqual(partner.region_names, ["Northern", "Eastern", "Western"])
        self.assertEqual(partner.region_name, "Northern")

    def test_the_edit_drawer_ticks_every_region_already_recorded(self):
        partner = Partner.objects.create(
            name="Ticked", region_name="Eastern", region_names=["Eastern", "Western"]
        )
        response = self.client.get(f"/partners/{partner.id}/edit-drawer")
        self.assertEqual(
            _region_boxes(response),
            {"Central": False, "Eastern": True, "Northern": False, "Western": True},
        )

    def test_a_region_the_list_no_longer_has_is_offered_ticked_so_it_is_not_lost(self):
        partner = Partner.objects.create(
            name="Legacy Region", region_name="West Nile", region_names=["West Nile"]
        )
        response = self.client.get(f"/partners/{partner.id}/edit-drawer")
        self.assertTrue(_region_boxes(response)["West Nile"])

    def test_a_region_stored_in_another_case_shows_ticked_under_the_list_spelling(self):
        partner = Partner.objects.create(
            name="Lower Case", region_name="northern", region_names=["northern"]
        )
        response = self.client.get(f"/partners/{partner.id}/edit-drawer")
        self.assertEqual(
            _region_boxes(response),
            {"Central": False, "Eastern": False, "Northern": True, "Western": False},
        )

    def test_unticking_every_region_clears_them(self):
        partner = Partner.objects.create(
            name="Untick Me", region_name="Central", region_names=["Central", "Eastern"]
        )
        response = self.client.post(
            f"/partners/{partner.id}/edit-drawer",
            {"name": "Untick Me", "contact_person": "", "email": "", "phone": ""},
        )
        self.assertEqual(response.status_code, 200)
        partner.refresh_from_db()
        self.assertEqual(partner.region_names, [])
        self.assertIsNone(partner.region_name)

    def test_the_profile_shows_every_region(self):
        partner = Partner.objects.create(
            name="Shown Everywhere",
            active_status=True,
            region_name="Northern",
            region_names=["Northern", "Eastern"],
        )
        response = self.client.get(f"/partners/{partner.id}")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Northern, Eastern")


@override_settings(ALLOWED_HOSTS=["testserver", "localhost"])
class SearchTest(TestCase):
    """HR, the RVP and the Project Coordinator read the partner workspace
    directly; searching it by a region finds every partner working there."""

    def setUp(self):
        self.hr = _user("regions-hr@edify.test", EdifyRole.HUMAN_RESOURCES.value)
        self.client.force_login(self.hr)
        self.two_regions = Partner.objects.create(
            name="North And East",
            active_status=True,
            region_name="Northern",
            region_names=["Northern", "Eastern"],
        )
        self.west = Partner.objects.create(
            name="West Only",
            active_status=True,
            region_name="Western",
            region_names=["Western"],
        )

    def _found(self, query):
        response = self.client.get("/partners", {"q": query})
        self.assertEqual(response.status_code, 200)
        return {card["partner"].name for card in response.context["partner_cards"]}

    def test_a_partner_is_found_by_a_region_that_is_not_its_first(self):
        self.assertEqual(self._found("eastern"), {"North And East"})

    def test_a_partner_is_still_found_by_its_first_region(self):
        self.assertEqual(self._found("Northern"), {"North And East"})
        self.assertEqual(self._found("Western"), {"West Only"})


@override_settings(ALLOWED_HOSTS=["testserver", "localhost"])
class DirectoryTableTest(TestCase):
    """The Partner Organisations table gives regions a column of their own,
    every region comma-separated (owner, 2026-09-23)."""

    def setUp(self):
        self.cd = _user("regions-table-cd@edify.test", EdifyRole.COUNTRY_DIRECTOR.value)
        self.client.force_login(self.cd)

    def test_every_region_sits_in_its_own_column(self):
        Partner.objects.create(
            name="Two Region Org",
            active_status=True,
            region_name="Northern",
            region_names=["Northern", "Eastern"],
        )
        Partner.objects.create(name="No Region Org", active_status=True)
        response = self.client.get("/admin-panel/users")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, ">Regions</th>", html=False)
        cells = re.findall(
            r"data-partner-regions>([^<]*)</td>", response.content.decode()
        )
        self.assertIn("Northern, Eastern", cells)
        self.assertIn("—", cells)
