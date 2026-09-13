from django.template.loader import render_to_string
from django.test import SimpleTestCase


class ClusterSsaAccordionTest(SimpleTestCase):
    def test_clusters_are_grouped_into_keyboard_accessible_district_disclosures(self):
        rows = [
            {"name": "East", "district": "Mukono", "cells": [], "overall": 6},
            {"name": "North", "district": "Kampala", "cells": [], "overall": 7},
            {"name": "West", "district": "Mukono", "cells": [], "overall": None},
        ]
        html = render_to_string(
            "partials/dashboards/pl/ssa_intelligence.html",
            {"ssa_matrix": {"rows": rows, "codes": []}},
        )
        self.assertEqual(html.count("data-ssa-district"), 2)
        self.assertEqual(html.count("<summary>"), 2)
        self.assertIn("Mukono <span>2 clusters</span>", html)
        self.assertLess(html.index("North"), html.index("East"))
        self.assertIn("No verified SSA", html)
