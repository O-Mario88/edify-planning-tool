"""Drill-down actions that know their subject, on every CD oversight page.

The analytics drawer's "Flag to Program Lead" and "Escalate to RVP" chips
were static links to empty forms; Team Oversight's country lens was read-only
while the near-identical Country Planning Oversight could send. Now the chips
carry the entity into the form they open, and both oversight pages let the
CD send a leadership ask (owner, 2026-09-03).
"""

from __future__ import annotations

from django.contrib.auth import get_user_model
from django.test import TestCase

from apps.accounts.models import StaffProfile
from apps.core.rbac import EdifyRole
from apps.geography.models import District, Region

User = get_user_model()


def _person(email, name, role):
    u = User.objects.create_user(
        email=email,
        name=name,
        roles=[role],
        active_role=role,
        password="x",
        is_active=True,
    )
    StaffProfile.objects.create(user=u, title=role, country="Uganda")
    return u


class ContextualActionsTest(TestCase):
    def setUp(self):
        self.cd = _person("act-cd@t.org", "Act CD", EdifyRole.COUNTRY_DIRECTOR.value)
        self.pl = _person(
            "act-pl@t.org", "Act PL", EdifyRole.COUNTRY_PROGRAM_LEAD.value
        )
        self.region = Region.objects.create(name="Act Region")
        self.district = District.objects.create(name="Act District", region=self.region)

    def test_drilldown_actions_carry_the_entity(self):
        from apps.analytics.cd_analytics_service import CDAnalyticsService

        data = CDAnalyticsService.drilldown(
            self.cd, "pl", {"id": self.pl.id}, fy="2026"
        )
        hrefs = {a["label"]: a["href"] for a in data["actions"]}
        self.assertIn(f"assign_to={self.pl.id}", hrefs["Flag to Program Lead"])
        self.assertIn("scope_type=pl", hrefs["Flag to Program Lead"])
        self.assertIn("scope_name=Act+PL", hrefs["Flag to Program Lead"])

        data = CDAnalyticsService.drilldown(
            self.cd, "district", {"id": self.district.id}, fy="2026"
        )
        hrefs = {a["label"]: a["href"] for a in data["actions"]}
        self.assertIn(f"scope_id={self.district.id}", hrefs["Flag to Program Lead"])
        data = CDAnalyticsService.drilldown(
            self.cd, "region", {"id": self.region.id}, fy="2026"
        )
        hrefs = {a["label"]: a["href"] for a in data["actions"]}
        self.assertIn("subject=Act+Region", hrefs["Escalate to RVP"])

    def test_the_flag_form_is_prefilled_from_the_drilldown(self):
        self.client.force_login(self.cd)
        response = self.client.get(
            f"/quality-checks?assign_to={self.pl.id}&scope_type=district&scope_id=d1&scope_name=Act%20District"
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "data-flag-scope")
        self.assertContains(response, f'value="{self.pl.id}" selected')
        self.assertContains(response, 'name="scope_name" value="Act District"')

    def test_the_escalation_form_is_prefilled_from_the_drilldown(self):
        self.client.force_login(self.cd)
        response = self.client.get(
            "/escalations?subject=Act%20Region&scope_type=region&scope_id=r1&scope_name=Act%20Region"
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'value="Act Region"')
        self.assertContains(response, 'name="scope_name" value="Act Region"')

    def test_team_oversight_country_lens_can_send(self):
        self.client.force_login(self.cd)
        response = self.client.get("/team-planning-oversight/")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["may_delegate"])
