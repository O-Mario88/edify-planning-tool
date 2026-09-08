"""One period, four country CSVs (owner, 2026-09-03).

The CD used to get one export: the PL roster. Risk, finance and core health
lived on screen only, so any figure carried into a board meeting was typed
by hand from a browser window.
"""

from __future__ import annotations

from django.contrib.auth import get_user_model
from django.test import TestCase

from apps.accounts.models import StaffProfile
from apps.analytics.cd_export_service import DATASETS, country_export, normalise_dataset
from apps.core.fy import get_operational_fy
from apps.core.rbac import EdifyRole

User = get_user_model()


def _person(email, role):
    u = User.objects.create_user(
        email=email,
        name=email,
        roles=[role],
        active_role=role,
        password="x",
        is_active=True,
    )
    StaffProfile.objects.create(user=u, title=role, country="Uganda")
    return u


class CountryExportSetTest(TestCase):
    def setUp(self):
        self.cd = _person("exp-cd@t.org", EdifyRole.COUNTRY_DIRECTOR.value)
        self.cceo = _person("exp-cceo@t.org", EdifyRole.CCEO.value)

    def test_every_dataset_downloads_as_csv_for_the_selected_period(self):
        self.client.force_login(self.cd)
        fy = get_operational_fy()
        for dataset in DATASETS:
            response = self.client.get(
                f"/analytics/country-director/export?set={dataset}&fy={fy}&quarter=Q1"
            )
            self.assertEqual(response.status_code, 200, dataset)
            self.assertEqual(response["Content-Type"], "text/csv")
            self.assertIn(f"-{fy}.csv", response["Content-Disposition"])
            first_line = response.content.decode().splitlines()[0]
            self.assertTrue(first_line, dataset)

    def test_the_four_datasets_carry_distinct_headers(self):
        seen = set()
        for dataset in DATASETS:
            slug, header, rows = country_export(
                self.cd, dataset, fy=get_operational_fy()
            )
            self.assertIsInstance(rows, list)
            seen.add((slug, tuple(header)))
        self.assertEqual(len(seen), 4)

    def test_an_unknown_set_falls_back_to_delivery(self):
        self.assertEqual(normalise_dataset("wat"), "delivery")
        self.assertEqual(normalise_dataset(None), "delivery")
        self.assertEqual(normalise_dataset(" Risk "), "risk")

    def test_the_page_offers_all_four_links_and_a_cceo_gets_nothing(self):
        self.client.force_login(self.cd)
        page = self.client.get("/analytics/country-director")
        self.assertEqual(page.status_code, 200)
        for dataset in DATASETS:
            self.assertContains(
                page, f"/analytics/country-director/export?set={dataset}"
            )
        self.client.force_login(self.cceo)
        response = self.client.get("/analytics/country-director/export?set=finance")
        self.assertNotEqual(response.status_code, 200)
        self.assertNotEqual(response.get("Content-Type"), "text/csv")
