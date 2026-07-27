import json
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase


class SubCountyMapAssetContractTest(SimpleTestCase):
    def test_index_and_lazy_assets_are_complete_and_display_only(self):
        geo_root = Path(settings.BASE_DIR) / "static" / "geo"
        index = json.loads((geo_root / "uganda_subcounty_index.json").read_text())

        self.assertEqual(index["audit"]["districts"], 135)
        self.assertEqual(index["audit"]["features"], 2205)
        self.assertEqual(index["audit"]["missing_districts"], [])
        self.assertEqual(
            index["usage"],
            "visualization_only_school_assignment_uses_saved_geography",
        )

        feature_total = 0
        codes = set()
        for entry in index["districts"].values():
            path = geo_root / entry["file"]
            self.assertTrue(path.is_file(), entry["file"])
            self.assertEqual(path.parent.name, "subcounties")

            payload = json.loads(path.read_text())
            self.assertTrue(payload["metadata"]["display_only"])
            self.assertTrue(payload["metadata"]["positive_area_overlaps_removed"])
            self.assertEqual(len(payload["features"]), entry["features"])

            feature_total += len(payload["features"])
            for feature in payload["features"]:
                properties = feature["properties"]
                self.assertEqual(
                    properties["od"].replace(" ", "").upper(),
                    entry["name"].replace(" ", "").upper(),
                )
                self.assertTrue(properties["n"])
                self.assertTrue(properties["k"])
                self.assertIsInstance(properties["a"], list)
                self.assertIn(
                    feature["geometry"]["type"],
                    {"Polygon", "MultiPolygon"},
                )
                self.assertNotIn(properties["c"], codes)
                codes.add(properties["c"])

        self.assertEqual(feature_total, 2205)
