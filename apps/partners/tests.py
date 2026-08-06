"""Partners service tests — ownership/scope check on update()."""

from django.contrib.auth import get_user_model
from django.test import TestCase

from apps.core.exceptions import Forbidden
from apps.core.rbac import EdifyRole
from apps.partners.models import Partner
from apps.partners.services import delete_partner, update


class PartnerUpdateScopeTests(TestCase):
    """Partner.update() previously had no ownership/scope check — any caller
    holding PARTNER_MANAGE (Admin, CountryDirector — both country-scoped
    roles) could update any partner by id, and nothing stopped a
    future/non-country-scoped PARTNER_MANAGE holder from mutating a partner
    outside their scope either. Mirrors the ownership check every other
    domain service applies before mutation (e.g. clusters._scope_filter)."""

    def setUp(self):
        User = get_user_model()
        self.partner = Partner.objects.create(name="Target Partner", active_status=True)
        self.admin_user = User.objects.create(
            id="admin-scope-1",
            email="admin-scope@edify.org",
            name="Admin User",
            roles=["Admin"],
            active_role="Admin",
            is_active=True,
        )
        self.cd_user = User.objects.create(
            id="cd-scope-1",
            email="cd-scope@edify.org",
            name="CD User",
            roles=["CountryDirector"],
            active_role="CountryDirector",
            is_active=True,
        )
        # A role with no country scope and no relationship to this partner at
        # all — simulates the "any caller holding PARTNER_MANAGE" scenario
        # the audit flagged even though no role today grants both.
        self.unscoped_user = User.objects.create(
            id="unscoped-scope-1",
            email="unscoped-scope@edify.org",
            name="Unscoped User",
            roles=["CCEO"],
            active_role="CCEO",
            is_active=True,
        )

    def test_country_scoped_roles_may_update_any_partner(self):
        result = update(self.partner.id, {"name": "Renamed By Admin"}, self.admin_user)
        self.assertEqual(result["name"], "Renamed By Admin")

        result = update(self.partner.id, {"name": "Renamed By CD"}, self.cd_user)
        self.assertEqual(result["name"], "Renamed By CD")

    def test_non_country_scoped_caller_outside_scope_is_forbidden(self):
        with self.assertRaises(Forbidden):
            update(self.partner.id, {"name": "Hijacked"}, self.unscoped_user)
        self.partner.refresh_from_db()
        self.assertNotEqual(self.partner.name, "Hijacked")


class OnboardPartnerSsaInterventionTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.cd_user = User.objects.create(
            id="cd-onboard-1",
            email="cd-onboard@edify.org",
            name="CD Onboarder",
            roles=["CountryDirector"],
            active_role="CountryDirector",
            is_active=True,
        )

    def test_onboard_partner_links_ssa_intervention(self):
        from apps.partners.services import onboard

        payload = {
            "name": "Christian Education Alliance",
            "regionName": "Central",
            "ssaIntervention": "christlike_behaviour",
            "contactPerson": "Alice",
            "email": "alice@cea.org",
            "phone": "+256 700 111 222",
        }
        res = onboard(payload, self.cd_user)
        self.assertEqual(res["name"], "Christian Education Alliance")
        self.assertEqual(res["ssaIntervention"], "christlike_behaviour")
        self.assertEqual(res["ssaInterventionLabel"], "Christlike Behaviour")

        partner = Partner.objects.get(id=res["id"])
        self.assertEqual(partner.ssa_intervention, "christlike_behaviour")
        self.assertEqual(partner.ssa_intervention_label, "Christlike Behaviour")


class PartnerDirectoryManagementTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.admin = User.objects.create_user(
            email="partner-admin@edify.test",
            name="Partner Admin",
            roles=[EdifyRole.ADMIN.value],
            active_role=EdifyRole.ADMIN.value,
            password="StrongPassphrase!23",
        )
        self.cd = User.objects.create_user(
            email="partner-cd@edify.test",
            name="Partner CD",
            roles=[EdifyRole.COUNTRY_DIRECTOR.value],
            active_role=EdifyRole.COUNTRY_DIRECTOR.value,
            password="StrongPassphrase!23",
        )
        self.hr = User.objects.create_user(
            email="partner-hr@edify.test",
            name="Partner HR",
            roles=[EdifyRole.HUMAN_RESOURCES.value],
            active_role=EdifyRole.HUMAN_RESOURCES.value,
            password="StrongPassphrase!23",
        )
        self.ia = User.objects.create_user(
            email="partner-ia@edify.test",
            name="Partner IA",
            roles=[EdifyRole.IMPACT_ASSESSMENT.value],
            active_role=EdifyRole.IMPACT_ASSESSMENT.value,
            password="StrongPassphrase!23",
        )

    def test_admin_and_cd_can_soft_delete_partners(self):
        admin_target = Partner.objects.create(name="Admin Removal Target")
        cd_target = Partner.objects.create(name="CD Removal Target")

        result = delete_partner(admin_target.id, self.admin)
        self.assertTrue(result["deleted"])
        self.assertFalse(Partner.objects.filter(id=admin_target.id).exists())
        tombstone = Partner.all_objects.get(id=admin_target.id)
        self.assertFalse(tombstone.active_status)
        self.assertIsNotNone(tombstone.deleted_at)

        delete_partner(cd_target.id, self.cd)
        self.assertFalse(Partner.objects.filter(id=cd_target.id).exists())

    def test_hr_and_ia_cannot_add_or_delete_partners(self):
        from apps.partners.services import onboard

        target = Partner.objects.create(name="Protected Partner")
        for principal in (self.hr, self.ia):
            with self.assertRaises(Forbidden):
                onboard({"name": f"Blocked {principal.name}"}, principal)
            with self.assertRaises(Forbidden):
                delete_partner(target.id, principal)
        self.assertTrue(Partner.objects.filter(id=target.id).exists())

    def test_users_page_is_the_cd_admin_partner_management_surface(self):
        Partner.objects.create(
            name="Visible Directory Partner",
            contact_person="Partner Contact",
            email="directory-partner@edify.test",
        )

        for principal in (self.admin, self.cd):
            self.client.force_login(principal)
            response = self.client.get("/admin-panel/users")
            self.assertEqual(response.status_code, 200)
            self.assertContains(response, "Partner Organisations")
            self.assertContains(response, "Visible Directory Partner")
            self.assertContains(response, "Add Partner")
            self.assertContains(response, "Remove Partner")

        self.client.force_login(self.hr)
        response = self.client.get("/admin-panel/users")
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "Partner Organisations")
        self.assertNotContains(response, "Visible Directory Partner")
        self.assertNotContains(response, "Add Partner")

    def test_users_page_create_and_delete_actions_enforce_role(self):
        self.client.force_login(self.cd)
        response = self.client.post(
            "/admin-panel/users",
            {
                "action": "create_partner",
                "partner_name": "Users Page Partner",
                "contact_person": "Amina",
                "partner_email": "users-page-partner@edify.test",
                "ssa_intervention": "christlike_behaviour",
            },
        )
        self.assertRedirects(
            response, "/admin-panel/users", fetch_redirect_response=False
        )
        partner = Partner.objects.get(name="Users Page Partner")

        self.client.force_login(self.hr)
        response = self.client.post(
            "/admin-panel/users",
            {"action": "delete_partner", "partner_id": partner.id},
        )
        self.assertRedirects(
            response, "/admin-panel/users", fetch_redirect_response=False
        )
        self.assertTrue(Partner.objects.filter(id=partner.id).exists())

        self.client.force_login(self.admin)
        response = self.client.post(
            "/admin-panel/users",
            {"action": "delete_partner", "partner_id": partner.id},
        )
        self.assertRedirects(
            response, "/admin-panel/users", fetch_redirect_response=False
        )
        self.assertFalse(Partner.objects.filter(id=partner.id).exists())
