"""A Programme Lead reads Who's Online for their own team.

Owner, 2026-09-22: "Give PLs access to Who is online but restrict to their team
members only."

The scoping itself is held in ``apps/accounts/test_presence.py``, where the
roster and every count are asserted against a real reporting line. What is held
here is the wiring: the Lead's Team view draws the shared panel, and the view
builds it for that view alone and always with a scope — an unscoped call on this
page would put the whole country on a Lead's screen.
"""

from pathlib import Path

from django.test import SimpleTestCase


ROOT = Path(__file__).resolve().parents[2]


class ProgrammeLeadTeamPresenceTest(SimpleTestCase):
    def test_the_team_view_draws_the_shared_panel(self):
        source = (ROOT / "templates/partials/dashboards/pl/team_view.html").read_text()
        self.assertIn('{% include "partials/dashboards/_whos_online.html" %}', source)
        # Guarded, so a view built without a roster draws no empty furniture.
        self.assertIn("{% if presence %}", source)

    def test_the_panel_says_whose_roster_it_is(self):
        panel = (ROOT / "templates/partials/dashboards/_whos_online.html").read_text()
        self.assertIn("presence_scope_label", panel)

    def test_the_lead_s_roster_is_never_built_without_a_scope(self):
        source = (ROOT / "apps/frontend/views/dashboard_views.py").read_text()
        block = source.split("def _program_lead_dashboard", 1)[1].split("\ndef ", 1)[0]
        self.assertIn("presence_summary(only_user_ids=team_user_ids(user))", block)
        # Built for the views that show it, not on every tab the Lead opens.
        self.assertIn('if view in ("week", "team"):', block)
        self.assertNotIn("presence_summary()", block)

    def test_the_main_dashboard_draws_the_team_panel(self):
        """Owner, 2026-09-24: Who's Online on the Lead's main dashboard, whose
        first view is This Week since 2026-09-26."""
        source = (ROOT / "templates/partials/dashboards/pl/week_view.html").read_text()
        self.assertIn('{% include "partials/dashboards/_whos_online.html" %}', source)
        self.assertIn("{% if presence %}", source)

    def test_the_lead_s_page_loads_the_panel_s_styles(self):
        """Without it the status lights were empty and folded groups open."""
        page = (ROOT / "templates/pages/dashboards/pl.html").read_text()
        self.assertIn("css/components/presence.css", page)
