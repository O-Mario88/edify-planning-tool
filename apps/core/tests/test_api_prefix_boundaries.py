from django.test import SimpleTestCase
from django.urls import resolve


class ApiPrefixBoundaryTests(SimpleTestCase):
    def test_collection_root_accepts_bare_and_slashed_forms(self):
        self.assertEqual(resolve("/api/schools").url_name, "list")
        self.assertEqual(resolve("/api/schools/").url_name, "list")

    def test_child_route_uses_exactly_one_boundary(self):
        self.assertEqual(resolve("/api/schools/bulk").url_name, "bulk")

    def test_concatenated_shadow_route_no_longer_resolves(self):
        from django.urls import Resolver404

        with self.assertRaises(Resolver404):
            resolve("/api/schoolsbulk")
