"""Country and regional oversight keep the full reporting roster in every period."""
from dataclasses import replace

from apps.accounts.models import StaffGeographyAssignment, StaffSupervisorAssignment
from apps.core.rbac import EdifyRole
from apps.frontend.test_planning_oversight_pages import OversightPageFixture, PL_URL
from apps.planning import oversight_service as oversight


class CompleteRosterTest(OversightPageFixture):
    def setUp(self):
        self.regional_user, regional = self._staff(
            "regional@t.test", "Regional Lead", EdifyRole.REGIONAL_PROGRAM_LEAD
        )
        StaffGeographyAssignment.objects.create(staff=regional, region_id=self.region.id)
        self.members = [self.james]
        for number in range(9):
            _, member = self._staff(f"member{number}@t.test", f"Member {number}", EdifyRole.CCEO)
            StaffSupervisorAssignment.objects.create(supervisor=self.pl, supervisee=member)
            self.members.append(member)
        self._activity(self.pl, self.school)
        self._activity(self.members[-1], self.school)

    def assert_roster(self, groups):
        self.assertEqual({g["id"] for g in groups}, {self.pl.id, *(p.id for p in self.members)})
        self.assertEqual(groups[0]["id"], self.pl.id)
        empty = next(g for g in groups if g["id"] == self.members[1].id)
        self.assertEqual(empty["items"], [])
        self.assertEqual(empty["summary"]["total_planned"], 0)

    def test_all_readers_see_the_full_roster_on_the_team_page(self):
        for user in (self.ia_user, self.cd_user, self.regional_user):
            with self.subTest(role=user.active_role):
                response = self.as_user(user).get(PL_URL, {"program_lead": self.pl.id, "fy": self.fy, "period": "fy"})
                self.assertEqual(response.status_code, 200)
                self.assert_roster(response.context["groups"])
                shown = [item for group in response.context["groups"] for item in group["items"]]
                self.assertEqual(len(shown), 3)
                self.assertNotIn(self.rival_activity.id, {item.activity_id for item in shown})

    def test_country_team_drawer_keeps_members_with_no_work(self):
        for user in (self.ia_user, self.cd_user):
            with self.subTest(role=user.active_role):
                response = self.as_user(user).get(
                    f"/country-planning-oversight/team/{self.pl.id}",
                    {"fy": self.fy, "period": "fy"},
                )
                self.assertEqual(response.status_code, 200)
                self.assert_roster(response.context["owner_groups"])
                self.assertEqual(sum(len(g["items"]) for g in response.context["owner_groups"]), 3)

    def test_empty_filtered_period_keeps_every_member(self):
        roster = oversight.program_lead_members(self.pl.id)
        self.assert_roster(oversight.group_by_owner([], owners=roster))

    def test_staff_and_user_ids_share_one_owner_group(self):
        items = oversight.build_items(self.cd_user, fy=self.fy)
        item = next(i for i in items if i.operational_owner_id == self.james.id)
        groups = oversight.group_by_owner(
            [item, replace(item, operational_owner_id=self.james_user.id)],
            owners=oversight.program_lead_members(self.pl.id),
        )
        self.assert_roster(groups)
        self.assertEqual(len(next(g for g in groups if g["id"] == self.james.id)["items"]), 2)
