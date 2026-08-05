"""A rate change has to say why, and the register has to show what happened.

Found during the §16 audit of the Country Director role. The backend was
already complete: `CostSettingHistory` is append-only, records old and new
value, version, actor and reason, and `budget.services.cost_setting_history`
returns it. None of that reached the interface.

Two consequences, both about the audit trail being real rather than nominal:

* The edit drawer had no reason input, and the view falls back to the literal
  string `"Updated via CD Dashboard"`. So every rate change ever made recorded
  who and when but not **why** — the only part anyone asks about later.
* The history was never rendered, so "what was this rate before, and who moved
  it" had no answer anywhere in the product.

This rate is the input to every activity budget in the country, which is why
the reason is required rather than optional. The fallback stays for API
callers that post without one.
"""

from __future__ import annotations

from django.contrib.auth import get_user_model
from django.contrib.sessions.middleware import SessionMiddleware
from django.test import RequestFactory, TestCase

from apps.budget.models import CostSetting, CostSettingHistory
from apps.budget.reference import CANONICAL_RATE_KEYS
from apps.frontend.views.finance_views import cost_setting_row_view

User = get_user_model()


class CostCatalogueRowUiTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.cd = User.objects.create(
            id="cc-cd",
            email="cc-cd@edify.org",
            name="CC Director",
            roles=["CountryDirector"],
            active_role="CountryDirector",
            is_active=True,
        )
        # post_migrate seeds the canonical register, so take the row that is
        # already there rather than creating a second one — `key` is unique.
        cls.key = sorted(CANONICAL_RATE_KEYS)[0]
        cls.setting, _ = CostSetting.objects.update_or_create(
            key=cls.key,
            defaults={"label": "CC Rate", "unit_cost": 100_000, "version": 1},
        )
        # Reference data may ship its own history; these tests assert on what
        # *this* test writes, so start from a known-empty trail.
        CostSettingHistory.objects.filter(key=cls.key).delete()

    def _call(self, method="GET", query="", data=None):
        factory = RequestFactory()
        request = (
            factory.post(f"/cost-settings/row/{self.key}", data)
            if method == "POST"
            else factory.get(f"/cost-settings/row/{self.key}{query}")
        )
        SessionMiddleware(lambda r: None).process_request(request)
        request.user = self.cd
        return cost_setting_row_view(request, self.key)

    # ── The reason ───────────────────────────────────────────────────────────

    def test_the_edit_drawer_asks_for_a_reason(self):
        body = self._call(query="?mode=edit").content.decode()
        self.assertIn('name="reason"', body)

    def test_the_reason_is_required_not_optional(self):
        """A rate feeds every activity budget in the country."""
        body = self._call(query="?mode=edit").content.decode()
        after_field = body.split('name="reason"', 1)[1][:300]
        self.assertIn("required", after_field)

    def test_a_supplied_reason_reaches_the_history_row(self):
        self._call(
            "POST", data={"unit_cost": "120000", "reason": "Fuel price revision"}
        )
        row = CostSettingHistory.objects.filter(key=self.key).latest("changed_at")
        self.assertEqual(row.reason, "Fuel price revision")
        self.assertNotEqual(
            row.reason,
            "Updated via CD Dashboard",
            "the boilerplate fallback must not win over a real reason",
        )

    def test_the_change_itself_is_recorded_with_both_values(self):
        self._call("POST", data={"unit_cost": "120000", "reason": "Fuel price"})
        row = CostSettingHistory.objects.filter(key=self.key).latest("changed_at")
        self.assertEqual(row.old_unit_cost, 100_000)
        self.assertEqual(row.new_unit_cost, 120_000)

    # ── The history panel ────────────────────────────────────────────────────

    def test_the_history_panel_is_rendered_in_the_drawer(self):
        body = self._call(query="?mode=edit").content.decode()
        self.assertIn("Change history", body)

    def test_a_past_change_and_its_reason_are_visible(self):
        self._call(
            "POST", data={"unit_cost": "120000", "reason": "Fuel price revision"}
        )
        body = self._call(query="?mode=edit").content.decode()
        self.assertIn("Fuel price revision", body)

    def test_the_actor_is_named_not_shown_as_an_id(self):
        """A user id in an audit table is not an answer to "who changed this"."""
        self._call("POST", data={"unit_cost": "120000", "reason": "Fuel price"})
        body = self._call(query="?mode=edit").content.decode()
        self.assertIn("CC Director", body)
        self.assertNotIn("cc-cd", body)

    def test_an_unchanged_rate_says_so_rather_than_showing_an_empty_table(self):
        body = self._call(query="?mode=edit").content.decode()
        self.assertIn("No recorded change yet", body)

    # ── The view mode is unaffected ──────────────────────────────────────────

    def test_the_read_only_row_does_not_load_history(self):
        """History is a query per row; the register lists 24 of them."""
        body = self._call(query="?mode=view").content.decode()
        self.assertNotIn("Change history", body)
