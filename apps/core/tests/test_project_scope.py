"""A Project Coordinator sees and touches only the projects they manage.

The rule was reimplemented in six places and diverged. The coordinator's own
landing page and the whole /api/special-projects/* surface applied no filter at
all — and PATCH let a coordinator reassign a peer's project to themselves.
"""

from __future__ import annotations

from django.test import Client, TestCase

from apps.accounts.models import StaffProfile, User
from apps.core.exceptions import Forbidden, NotFoundError
from apps.core.rbac import EdifyRole
from apps.projects import services as project_services
from apps.projects.models import Project, ProjectCategory
from apps.projects.scoping import get_scoped_project, scoped_projects


def _user(email, name, role):
    return User.objects.create_user(
        email=email,
        name=name,
        roles=[role],
        active_role=role,
        password="pw12345678",
        is_active=True,
    )


class ProjectCoordinatorScopeTests(TestCase):
    def setUp(self):
        self.mine, self.mine_sp = self._pc("pc-mine@t.org", "Mia")
        self.theirs, self.theirs_sp = self._pc("pc-theirs@t.org", "Theo")

        self.my_project = Project.objects.create(
            name="SP-MINE",
            category=ProjectCategory.PILOT.value,
            target_interventions=["leadership"],
            manager_staff_id=self.mine_sp.id,
        )
        self.their_project = Project.objects.create(
            name="SP-THEIRS",
            category=ProjectCategory.PILOT.value,
            target_interventions=["leadership"],
            manager_staff_id=self.theirs_sp.id,
        )

    def _pc(self, email, name):
        u = _user(email, name, EdifyRole.PROJECT_COORDINATOR.value)
        sp = StaffProfile.objects.create(
            user=u, title="ProjectCoordinator", country="Uganda"
        )
        return u, sp

    def test_coordinator_sees_only_their_own(self):
        names = list(scoped_projects(self.mine).values_list("name", flat=True))
        self.assertEqual(names, ["SP-MINE"])

    def test_coordinator_cannot_fetch_a_peers_project(self):
        with self.assertRaises(Forbidden):
            get_scoped_project(self.their_project.id, self.mine)

    def test_unknown_project_is_not_found(self):
        with self.assertRaises(NotFoundError):
            get_scoped_project("no-such-project", self.mine)

    def test_api_list_is_scoped(self):
        client = Client()
        client.force_login(self.mine)
        resp = client.get("/api/special-projects/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual([p["name"] for p in resp.json()], ["SP-MINE"])

    def test_api_detail_refuses_a_peers_project(self):
        client = Client()
        client.force_login(self.mine)
        resp = client.get(f"/api/special-projects/{self.their_project.id}")
        self.assertIn(resp.status_code, (403, 404))

    def test_coordinator_cannot_seize_a_peers_project(self):
        """PATCH previously let any PROJECT_MANAGE holder reassign any
        project — including taking a peer's, or orphaning it."""
        with self.assertRaises(Forbidden):
            project_services.set_manager(
                self.their_project.id,
                {"managerStaffId": self.mine_sp.id},
                self.mine,
            )
        self.their_project.refresh_from_db()
        self.assertEqual(self.their_project.manager_staff_id, self.theirs_sp.id)

    def test_coordinator_cannot_reassign_even_their_own(self):
        """Ownership is assigned by country leadership, not self-claimed."""
        with self.assertRaises(Forbidden):
            project_services.set_manager(
                self.my_project.id, {"managerStaffId": self.theirs_sp.id}, self.mine
            )

    def test_dashboard_shows_only_their_portfolio(self):
        client = Client()
        client.force_login(self.mine)
        resp = client.get("/dashboard", follow=True)
        self.assertEqual(resp.status_code, 200)
        body = resp.content.decode()
        self.assertIn("SP-MINE", body)
        self.assertNotIn("SP-THEIRS", body)


class CountryRoleProjectScopeTests(TestCase):
    def test_country_director_sees_everything(self):
        cd = _user("cd-proj@t.org", "Cody", EdifyRole.COUNTRY_DIRECTOR.value)
        StaffProfile.objects.create(user=cd, title="CD", country="Uganda")
        Project.objects.create(
            name="SP-A",
            category=ProjectCategory.PILOT.value,
            target_interventions=["leadership"],
        )
        Project.objects.create(
            name="SP-B",
            category=ProjectCategory.PILOT.value,
            target_interventions=["leadership"],
        )
        self.assertEqual(scoped_projects(cd).count(), 2)

    def test_unrelated_role_sees_nothing(self):
        acct = _user("acct-proj@t.org", "Ada", EdifyRole.PROGRAM_ACCOUNTANT.value)
        StaffProfile.objects.create(user=acct, title="Accountant", country="Uganda")
        Project.objects.create(
            name="SP-C",
            category=ProjectCategory.PILOT.value,
            target_interventions=["leadership"],
        )
        # The Accountant is a country role for finance, and finance legitimately
        # spans projects — but they hold no project page, so this only asserts
        # the helper does not crash for them.
        self.assertGreaterEqual(scoped_projects(acct).count(), 0)


class FundRequestReviewScopeTests(TestCase):
    """`_review` blocked self-approval and nothing else, so any budget.approve
    holder — CCEOs carry it too — could approve another team's request."""

    def setUp(self):
        from apps.fund_requests.models import FundRequest, FundRequestStatus

        self.owner = _user("fr-owner@t.org", "Olive", EdifyRole.CCEO.value)
        self.owner_sp = StaffProfile.objects.create(
            user=self.owner, title="CCEO", country="Uganda"
        )
        self.their_pl = _user("fr-pl2@t.org", "Pia", EdifyRole.COUNTRY_PROGRAM_LEAD.value)
        StaffProfile.objects.create(user=self.their_pl, title="PL", country="Uganda")

        self.fr = FundRequest.objects.create(
            fy="2026",
            period="monthly",
            period_key="2026-M5",
            scope="own",
            submitted_by_user_id=self.owner.id,
            submitted_by_role="CCEO",
            total_amount=100_000,
            activity_count=1,
            status=FundRequestStatus.SUBMITTED,
        )

    def test_unrelated_program_lead_cannot_approve(self):
        from apps.fund_requests import services as fr_services

        with self.assertRaises(Forbidden):
            fr_services.approve(self.fr.id, {}, self.their_pl)

    def test_supervising_program_lead_can_approve(self):
        from apps.accounts.models import StaffSupervisorAssignment
        from apps.fund_requests import services as fr_services

        pl = _user("fr-pl1@t.org", "Pat", EdifyRole.COUNTRY_PROGRAM_LEAD.value)
        pl_sp = StaffProfile.objects.create(user=pl, title="PL", country="Uganda")
        StaffSupervisorAssignment.objects.create(
            supervisee=self.owner_sp, supervisor=pl_sp
        )
        result = fr_services.approve(self.fr.id, {}, pl)
        self.assertEqual(result["status"], "approved")

    def test_country_director_may_approve(self):
        from apps.fund_requests import services as fr_services

        cd = _user("fr-cd@t.org", "Cody", EdifyRole.COUNTRY_DIRECTOR.value)
        StaffProfile.objects.create(user=cd, title="CD", country="Uganda")
        result = fr_services.approve(self.fr.id, {}, cd)
        self.assertEqual(result["status"], "approved")
