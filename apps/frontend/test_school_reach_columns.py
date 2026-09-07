"""School reach on every district table.

The owner asked District monitoring for # Schools, # Planned, # Achieved and
% Achieved, then asked whether the other roles' district tables carried them
(2026-09-05). Every delivery-by-district surface does now: IA District
monitoring, the CD dashboard's region and district breakdown, the Program
Lead's district performance, and the overview's geographic priorities. Tables
that measure something else — SSA scores by district, visit coverage — keep
their own columns.
"""

from pathlib import Path

from django.test import SimpleTestCase


ROOT = Path(__file__).resolve().parents[2]


def _read(relative_path: str):
    from apps.frontend.template_families import read_template

    return read_template(ROOT, relative_path)


HEADERS = ("# Schools", "# Planned", "# Achieved", "% Achieved")


class SchoolReachColumnsTest(SimpleTestCase):
    def test_every_delivery_by_district_table_carries_the_school_bands(self):
        for path in (
            "templates/partials/ia/dashboard_body.html",
            "templates/partials/dashboards/cd/body.html",
            "templates/partials/analytics/pl/district_performance.html",
            "templates/partials/analytics/target_by_district.html",
        ):
            source = _read(path)
            for header in HEADERS:
                with self.subTest(path=path, header=header):
                    self.assertIn(header, source)

    def test_every_district_builder_counts_schools_not_activities(self):
        for path, marker in (
            (
                "apps/frontend/views/ia_views.py",
                '"schools_planned": len(planned_schools_by_district',
            ),
            (
                "apps/analytics/cd_dashboard_service.py",
                'b["planned_schools"].add(a["school_id"])',
            ),
            (
                "apps/analytics/pl_analytics_service.py",
                "district_planned_schools.setdefault(did, set()).add(sid)",
            ),
            (
                "apps/analytics/analytics_dashboard_service.py",
                'planned_schools=Count("school_id", distinct=True)',
            ),
        ):
            with self.subTest(path=path):
                source = _read(path)
                self.assertIn(marker, source)
                self.assertIn('"schools_pct"', source)

    def test_the_program_lead_list_became_a_table_that_still_opens_the_drawer(self):
        source = _read("templates/partials/analytics/pl/district_performance.html")
        self.assertIn('class="w-full text-left text-[12px] pl-district-table"', source)
        self.assertIn(
            "/analytics/program-lead/drilldown?drill=district&id={{ d.id }}", source
        )
        self.assertIn("hx-trigger=\"click, keyup[key=='Enter']\"", source)
