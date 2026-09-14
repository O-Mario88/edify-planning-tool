"""A link is only shown to someone who can follow it (visual test, 2026-09-14).

Partner, MFI and Project Coordinator pages linked into pages that refuse those
roles: a partner's calendar offered Apply for Leave, its completed-work table
linked school and cluster profiles, My Targets linked My Performance and
Priorities, a role home's primary action pointed an MFI admin at Business
Transformation, and a Coordinator's Cluster Required rows pointed at Clusters.
Each case renders the page for the refused role and for a role the target page
admits, so a gate that hid the link from everyone would fail here too.

The same day the owner removed the blocking policy gate: a partner who has not
answered a mandatory policy reaches their home, and the service worker loads.
"""

from __future__ import annotations

from django.template.loader import render_to_string
from django.test import RequestFactory, TestCase, override_settings

from apps.accounts.models import StaffProfile, User
from apps.activities.models import Activity
from apps.clusters.models import Cluster
from apps.core.fy import get_operational_fy, get_quarter_for_date
from apps.documents.models import AcknowledgementState, DocumentAcknowledgement
from apps.documents.services import DocumentService
from apps.documents.tests import DocumentTestBase
from apps.geography.models import District, Region
from apps.partners.models import Partner
from apps.projects.models import Project, ProjectSchoolAssignment
from apps.schools.models import School

LOCMEM = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "link-gates-partner-home",
    }
}


def _user(key, role, *, staff=False):
    user = User.objects.create(
        id=f"lgph-{key}"[:30],
        email=f"lgph-{key}@edify.org",
        name=f"LG {key}",
        roles=[role],
        active_role=role,
        is_active=True,
    )
    if staff:
        StaffProfile.objects.create(user=user, title=role, country="Uganda")
    return user


def _place():
    region = Region.objects.create(name="Link Gate Region")
    district = District.objects.create(name="Link Gate District", region=region)
    return region, district


@override_settings(CACHES=LOCMEM)
class CalendarLeaveActionTest(TestCase):
    def test_a_partner_is_not_offered_apply_for_leave(self):
        self.client.force_login(_user("cal-partner", "PartnerFieldOfficer"))
        response = self.client.get("/calendar")
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'href="/personal-time-off"')
        self.assertNotContains(response, "Apply for Leave")

    def test_a_cceo_still_applies_for_leave_from_the_calendar(self):
        self.client.force_login(_user("cal-cceo", "CCEO", staff=True))
        response = self.client.get("/calendar")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'href="/personal-time-off"')


@override_settings(CACHES=LOCMEM)
class PartnerCompletedRecordLinksTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        region, district = _place()
        cls.school = School.objects.create(
            school_id="LGPH-001",
            name="Link Gate Primary",
            region=region,
            district=district,
        )
        cls.cluster = Cluster.objects.create(
            name="Link Gate Cluster", region=region, district=district
        )
        cls.partner_user = _user("done-partner", "PartnerFieldOfficer")
        cls.admin = _user("done-admin", "Admin")
        cls.partner = Partner.objects.create(
            name="Link Gate Partner", user_id=cls.partner_user.id, active_status=True
        )
        fy, quarter = get_operational_fy(), get_quarter_for_date()
        for activity_type, where in (
            ("school_visit", {"school": cls.school}),
            ("cluster_meeting", {"cluster": cls.cluster}),
        ):
            Activity.objects.create(
                activity_type=activity_type,
                fy=fy,
                quarter=quarter,
                assigned_partner_id=cls.partner.id,
                status="completed",
                **where,
            )

    def _get(self, user, path):
        self.client.force_login(user)
        response = self.client.get(path)
        self.assertEqual(response.status_code, 200)
        return response

    def test_a_partner_reads_the_school_and_cluster_without_a_dead_link(self):
        schools = self._get(self.partner_user, "/partner/completed")
        self.assertContains(schools, "Link Gate Primary")
        self.assertNotContains(schools, f'href="/schools/{self.school.id}"')

        activities = self._get(self.partner_user, "/partner/completed?tab=activities")
        self.assertContains(activities, "Link Gate Cluster")
        self.assertNotContains(activities, f'href="/clusters/{self.cluster.id}"')

    def test_an_admin_still_opens_the_school_and_cluster(self):
        Partner.objects.filter(id=self.partner.id).update(user_id=self.admin.id)

        schools = self._get(self.admin, "/partner/completed")
        self.assertContains(schools, f'href="/schools/{self.school.id}"')

        activities = self._get(self.admin, "/partner/completed?tab=activities")
        self.assertContains(activities, f'href="/clusters/{self.cluster.id}"')


@override_settings(CACHES=LOCMEM)
class MyTargetsLinksTest(TestCase):
    def _body(self, user):
        self.client.force_login(user)
        response = self.client.get("/my-targets", HTTP_HX_REQUEST="true")
        self.assertEqual(response.status_code, 200)
        return response

    def test_a_partner_is_not_linked_to_my_performance_or_priorities(self):
        response = self._body(_user("tg-partner", "PartnerFieldOfficer"))
        self.assertNotContains(response, 'href="/my-performance"')
        self.assertNotContains(response, 'href="/priorities')

    def test_a_cceo_keeps_both_links(self):
        response = self._body(_user("tg-cceo", "CCEO", staff=True))
        self.assertContains(response, 'href="/my-performance"')
        self.assertContains(response, 'href="/priorities?fy=')


@override_settings(CACHES=LOCMEM)
class MobileHomeActionTest(TestCase):
    """The shared role-home and agenda-card actions ask the target page."""

    def _render(self, template, user, context):
        request = RequestFactory().get("/")
        request.user = user
        return render_to_string(template, {"request": request, **context})

    def test_the_primary_action_renders_only_for_a_role_its_page_admits(self):
        context = {
            "headline": "Home",
            "primary_action": {
                "label": "Open Business Transformation",
                "url": "/business-transformation",
            },
        }
        mfi = _user("home-mfi", "MfiPartnerAdmin")
        officer = _user("home-bt", "BusinessTransformationOfficer")

        refused = self._render("components/mobile_role_home.html", mfi, context)
        admitted = self._render("components/mobile_role_home.html", officer, context)

        self.assertIn("data-mobile-role-home", refused)
        self.assertNotIn('href="/business-transformation"', refused)
        self.assertIn('href="/business-transformation"', admitted)

    def test_an_mfi_admin_keeps_an_action_it_can_open(self):
        html = self._render(
            "components/mobile_role_home.html",
            _user("home-mfi-todo", "MfiPartnerAdmin"),
            {"headline": "Home", "primary_action": {"label": "Tasks", "url": "/todos"}},
        )
        self.assertIn('href="/todos"', html)

    def test_the_agenda_card_action_renders_only_for_a_role_its_page_admits(self):
        item = {"title": "Portfolio review", "action_url": "/business-transformation"}
        mfi = _user("agenda-mfi", "MfiPartnerAdmin")
        officer = _user("agenda-bt", "BusinessTransformationOfficer")

        refused = self._render(
            "components/mobile_agenda_card.html", mfi, {"item": item}
        )
        admitted = self._render(
            "components/mobile_agenda_card.html", officer, {"item": item}
        )

        self.assertIn("Portfolio review", refused)
        self.assertNotIn("mobile-agenda-card__action", refused)
        self.assertIn('href="/business-transformation"', admitted)


@override_settings(CACHES=LOCMEM)
class ProjectClusterRequiredLinkTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        region, district = _place()
        cls.coordinator = _user("pc", "ProjectCoordinator", staff=True)
        cls.admin = _user("pc-admin", "Admin")
        school = School.objects.create(
            school_id="LGPH-PC-1",
            name="Clusterless Project School",
            region=region,
            district=district,
            current_fy_ssa_status="done",
            planning_readiness="requires_cluster",
        )
        project = Project.objects.create(
            name="Link Gate Project",
            category="pilot",
            manager_staff_id=cls.coordinator.staff_profile.id,
        )
        ProjectSchoolAssignment.objects.create(project=project, school=school)

    def test_a_coordinator_sees_cluster_required_without_a_dead_link(self):
        self.client.force_login(self.coordinator)
        response = self.client.get("/projects")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Cluster Required")
        self.assertNotContains(response, 'href="/clusters"')
        self.assertNotContains(response, "Add to Cluster →")

    def test_an_admin_is_still_sent_to_clusters(self):
        self.client.force_login(self.admin)
        response = self.client.get("/projects")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Add to Cluster →</a>")

    def test_the_coordinator_action_centre_drops_the_clusters_step(self):
        item = {
            "project": "Link Gate Project",
            "issue": "Cluster Required",
            "title": "Clusterless Project School",
            "detail": "Move this school to its next project-planning step.",
            "tone": "neutral",
            "priority_label": "Needs planning",
            "url": "/clusters",
            "action_label": "Add to Cluster",
        }

        def render(user):
            request = RequestFactory().get("/dashboard")
            request.user = user
            return render_to_string(
                "partials/dashboards/special_projects/operations.html",
                {"request": request, "action_queue": [item], "action_count": 1},
            )

        refused = render(self.coordinator)
        self.assertIn("Clusterless Project School", refused)
        self.assertNotIn('href="/clusters"', refused)
        self.assertIn('href="/clusters"', render(self.admin))


@override_settings(CACHES=LOCMEM)
class PartnerHomeWithoutPolicyGateTest(DocumentTestBase):
    """An unanswered blocking policy no longer withholds a partner's home."""

    def setUp(self):
        self.partner_admin = _user("gate-partner-admin", "PartnerAdmin")
        document, version = self._policy(title="Partner Safeguarding Policy")
        DocumentService.set_audience(self.hr, document, [{"role": "PartnerAdmin"}])
        self._publish(document, version)
        self.assertTrue(
            DocumentAcknowledgement.objects.filter(
                version=version,
                user_id=self.partner_admin.id,
                state=AcknowledgementState.PENDING,
            ).exists()
        )
        self.client.force_login(self.partner_admin)

    def test_the_dashboard_opens_without_the_agreement_detour(self):
        response = self.client.get("/dashboard", follow=True)
        self.assertEqual(response.status_code, 200)
        hops = [url for url, _ in response.redirect_chain]
        self.assertFalse(
            any(hop.startswith(("/policy-agreement", "/documents/")) for hop in hops),
            hops,
        )

    def test_the_service_worker_loads(self):
        self.assertEqual(self.client.get("/sw.js").status_code, 200)

    def test_the_agreement_center_still_opens_the_policy(self):
        response = self.client.get("/policy-agreement", follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Partner Safeguarding Policy")
