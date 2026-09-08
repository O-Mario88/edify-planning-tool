"""Every filter a page draws must reach the code that answers the page.

The 2026-09-06 filter audit read every filter control on every filtered page
and compared it against the parameters its view actually reads. Three controls
opened, offered choices and changed nothing:

  * `/admin-panel/users` carried the active search as `user_query`, a name that
    appears in no Python file — the view reads `q` — so choosing a role or a
    status silently threw the search away.
  * `/analytics/country-director` drew a Region select that `_cd_filters` never
    put in the filter dict, though the service has always scoped schools by
    region_id.
  * `/analytics/visit-effectiveness` drew an "Assessment comparison" select
    with one hardcoded option that no view has ever read.

The audit also found the reverse: `/planning` honoured `fy` and `ssa_status`
and its view supplied the options for both, but neither control was drawn, so
the page was locked to the operational year and could not be narrowed to the
schools whose assessment is outstanding.

This module keeps all four honest. A rendered control that no view reads is a
lie about what the page can do, and it is not visible in any test that only
checks status codes.
"""

from __future__ import annotations

import re
from pathlib import Path

from django.test import SimpleTestCase

ROOT = Path(__file__).resolve().parents[2]


def _read(relative_path: str) -> str:
    return (ROOT / relative_path).read_text()


def _control_names(markup: str) -> set[str]:
    """Every name a form control posts, filter or otherwise."""
    return set(re.findall(r'name="([a-z_]+)"', markup))


class FilterReachesItsViewTest(SimpleTestCase):
    def test_admin_user_search_survives_a_role_or_status_change(self):
        page = _read("templates/pages/admin/users.html")
        view = _read("apps/frontend/views/extended_views.py")
        self.assertIn('request.GET.get("q"', view)
        self.assertNotIn("user_query", _control_names(page))
        # The top-bar search is bound to the filter form, so submitting the
        # form carries `q` — the platform's one-search pattern, and the reason
        # no page may grow a body search of its own (test_search_consolidation).
        self.assertIn('id="admin-users-filters"', page)
        self.assertIn('"attach_to": "admin-users-filters"', view)
        self.assertIn('"name": "q"', view)

    def test_cd_analytics_passes_region_to_the_service(self):
        view = _read("apps/frontend/views/analytics_views.py")
        panel = _read("templates/partials/analytics/panels/cd_overview.html")
        service = _read("apps/analytics/cd_analytics_service.py")
        # The control exists, the view forwards it, the service reads it.
        self.assertIn('name="region"', panel)
        self.assertIn('"region": request.GET.get("region")', view)
        self.assertIn('filters.get("region")', service)

    def test_visit_effectiveness_states_its_comparison_instead_of_offering_it(self):
        panel = _read("templates/partials/analytics/panels/visit_effectiveness.html")
        self.assertNotIn('name="comparison"', panel)
        self.assertIn("SSA performance FY", panel)
        # The one control that IS read stays.
        self.assertIn('name="school_type"', panel)

    def test_planning_draws_the_filters_it_honours(self):
        page = _read("templates/pages/planning/index.html")
        view = _read("apps/frontend/views/planning_views.py")
        for param in ("fy", "ssa_status"):
            with self.subTest(param=param):
                self.assertIn(f'"{param}": request.GET.get("{param}"', view)
                self.assertIn(f'name="{param}"', page)
        # And the options both need are still built for the template.
        self.assertIn('"fy_options": fy_options()', view)
        self.assertIn('"ssa_statuses": SsaStatus.choices', view)


class EmptyFilterTest(SimpleTestCase):
    """A filter with nothing to choose is hidden, not drawn.

    Several controls derive their options from the data in view — Notifications
    lists only the categories that reader actually has, the Accountant's
    District select lists only districts present in the fund queue. When that
    comes back empty the control is a dropdown that opens on one line, which
    the reader still has to read and dismiss. micro-ux hides those and leaves
    everything else alone.
    """

    def setUp(self):
        self.js = _read("static/js/micro-ux.js")

    def test_the_pass_runs_with_the_other_writers(self):
        self.assertIn("function hideEmptyFilters(root)", self.js)
        self.assertIn("hideEmptyFilters(root);", self.js)

    def test_only_a_control_with_nothing_to_choose_is_hidden(self):
        self.assertIn("select.options.length < 2 && !applied", self.js)

    def test_a_control_narrowed_by_an_active_filter_stays(self):
        """Hiding it would strand the reader with a filter they cannot clear."""
        self.assertIn(
            "var applied = select.value && select.value !== 'all' && select.value !== 'All';",
            self.js,
        )

    def test_the_field_is_hidden_rather_than_removed(self):
        """It still posts its value, so the server sees the same form."""
        self.assertIn("shell.hidden = true;", self.js)
        self.assertIn("data-edify-filter-empty", self.js)
        self.assertNotIn("shell.remove()", self.js)
