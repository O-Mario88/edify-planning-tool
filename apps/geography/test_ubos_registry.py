import json
import tempfile
from pathlib import Path

from django.test import SimpleTestCase, TestCase

from apps.geography.models import District, Region, SubCounty
from apps.geography.ubos_registry import (
    district_canonical,
    ensure_ubos_subcounties,
    load_registry,
)


class UbosRegistrySourceContractTest(SimpleTestCase):
    def test_committed_registry_has_current_spatial_inventory(self):
        payload = load_registry()

        self.assertEqual(payload["record_count"], 2208)
        self.assertEqual(payload["spatial_record_count"], 2205)
        self.assertEqual(payload["non_spatial_record_count"], 3)
        self.assertEqual(
            sum(bool(row["has_geometry"]) for row in payload["records"]),
            2205,
        )

    def test_city_and_new_districts_use_the_overview_parent_contract(self):
        self.assertEqual(district_canonical("Gulu City"), "GULU")
        self.assertEqual(district_canonical("Fort Portal City"), "KABAROLE")
        self.assertEqual(district_canonical("Terego"), "ARUA")
        self.assertEqual(district_canonical("Luwero"), "LUWEERO")


class UbosRegistrySyncTest(TestCase):
    def setUp(self):
        self.region = Region.objects.create(name="Northern")
        self.gulu = District.objects.create(name="Gulu", region=self.region)
        self.adjumani = District.objects.create(
            name="Adjumani",
            region=self.region,
        )

    def _registry(self, records):
        handle = tempfile.NamedTemporaryFile(
            mode="w",
            suffix=".json",
            delete=False,
        )
        json.dump(
            {
                "record_count": len(records),
                "records": records,
            },
            handle,
        )
        handle.close()
        self.addCleanup(Path(handle.name).unlink, missing_ok=True)
        return Path(handle.name)

    def _row(
        self,
        *,
        code,
        name,
        district,
        county="Test County",
        spatial=True,
    ):
        return {
            "code": code,
            "name": name,
            "district_name": district,
            "county_name": county,
            "has_geometry": spatial,
        }

    def test_sync_is_additive_idempotent_and_folds_city_children(self):
        legacy = SubCounty.objects.create(name="Bungatira", district=self.gulu)
        path = self._registry(
            [
                self._row(
                    code="301101",
                    name="BUNGATIRA",
                    district="GULU",
                ),
                self._row(
                    code="301102",
                    name="BAR DEGE-LAYIBI DIVISION",
                    district="GULU CITY",
                ),
                self._row(
                    code="301999",
                    name="REPORTING CAMP",
                    district="GULU",
                    spatial=False,
                ),
            ]
        )

        first = ensure_ubos_subcounties(path=path)
        second = ensure_ubos_subcounties(path=path)

        legacy.refresh_from_db()
        self.assertIsNone(legacy.pcode)
        self.assertIsNone(legacy.source)
        self.assertEqual(first["created"], 1)
        self.assertEqual(first["matched_by_name"], 1)
        self.assertEqual(first["non_spatial_excluded"], 1)
        self.assertEqual(second["created"], 0)
        city_row = SubCounty.objects.get(pcode="301102")
        self.assertEqual(city_row.district, self.gulu)
        self.assertEqual(city_row.source, "UBOS_NPHC_2024_LIVE")

    def test_duplicate_official_labels_are_disambiguated_by_county(self):
        path = self._registry(
            [
                self._row(
                    code="301107",
                    name="REFUGEE SETTLEMENT CAMPS",
                    district="ADJUMANI",
                    county="Adjumani County",
                ),
                self._row(
                    code="301206",
                    name="REFUGEE SETTLEMENT CAMPS",
                    district="ADJUMANI",
                    county="East Moyo County",
                ),
            ]
        )

        stats = ensure_ubos_subcounties(path=path)

        self.assertEqual(stats["created"], 2)
        self.assertCountEqual(
            SubCounty.objects.filter(district=self.adjumani).values_list(
                "name",
                flat=True,
            ),
            [
                "Refugee Settlement Camps — Adjumani County",
                "Refugee Settlement Camps — East Moyo County",
            ],
        )

    def test_dry_run_reports_without_writing(self):
        path = self._registry(
            [
                self._row(
                    code="301102",
                    name="BAR DEGE-LAYIBI DIVISION",
                    district="GULU CITY",
                )
            ]
        )

        stats = ensure_ubos_subcounties(path=path, dry_run=True)

        self.assertEqual(stats["planned_create"], 1)
        self.assertEqual(stats["created"], 0)
        self.assertFalse(SubCounty.objects.filter(pcode="301102").exists())
