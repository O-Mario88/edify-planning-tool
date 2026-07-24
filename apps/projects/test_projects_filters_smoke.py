from django.test import Client, TestCase
from apps.accounts.models import User
from apps.core.rbac import EdifyRole
from apps.projects.models import Project, ProjectCategory


def _user(email, name, role):
    u = User.objects.create_user(email=email, name=name, roles=[role], active_role=role,
                                 password="pw12345678", is_active=True)
    return u


class ProjectsFiltersSmokeTests(TestCase):
    def setUp(self):
        self.admin = _user("admin@t.org", "Admin", EdifyRole.ADMIN.value)
        self.pilot = Project.objects.create(name="SP-PILOT", code="SP-PILOT",
                                            category=ProjectCategory.PILOT.value)
        self.intv = Project.objects.create(name="SP-INTV", code="SP-INTV",
                                           category=ProjectCategory.INTERVENTION_SPECIFIC.value)
        self.c = Client()
        self.c.force_login(self.admin)

    def test_default_view_renders(self):
        r = self.c.get("/projects")
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "SP-PILOT")
        self.assertContains(r, "SP-INTV")
        # filter form is wired now
        self.assertContains(r, 'name="fy"')
        self.assertContains(r, 'name="type"')
        self.assertContains(r, 'name="status"')
        # drawer route is live, not a 404 link
        self.assertContains(r, '/projects/filters-drawer')
        self.assertContains(r, 'id="project-list"')

    def test_filtered_view_by_type(self):
        r = self.c.get("/projects/filter", {"type": ProjectCategory.PILOT.value})
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "SP-PILOT")
        self.assertNotContains(r, "SP-INTV")

    def test_filtered_view_no_params_redirects_to_default(self):
        r = self.c.get("/projects/filter")
        self.assertEqual(r.status_code, 302)
        self.assertEqual(r.headers.get("Location"), "/projects")

    def test_drawer_view_renders(self):
        r = self.c.get("/projects/filters-drawer")
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Filter Projects")
        self.assertContains(r, "Project Type")

    def test_htmx_partial_branch(self):
        r = self.c.get("/projects", {"type": ProjectCategory.PILOT.value},
                       HTTP_HX_TARGET="project-list")
        self.assertEqual(r.status_code, 200)
        # partial should NOT contain the full page chrome
        self.assertNotContains(r, "Upcoming Follow-Ups")
        self.assertContains(r, "SP-PILOT")

    def test_bad_params_rejected_safely(self):
        r = self.c.get("/projects/filter", {"type": "does_not_exist"})
        # no valid filter -> redirect to default
        self.assertEqual(r.status_code, 302)
