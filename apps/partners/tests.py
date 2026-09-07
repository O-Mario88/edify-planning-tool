"""Partners service tests — ownership/scope check on update()."""

from django.contrib.auth import get_user_model
from django.test import TestCase

from apps.core.exceptions import ConflictError, Forbidden
from apps.core.rbac import EdifyRole
from apps.partners.models import Partner
from apps.partners.services import (
    add_member,
    delete_partner,
    onboard,
    purge_partner,
    remove_member,
    set_partner_status,
    update,
)


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
        # A removed organisation is a row whose Status says so (owner,
        # 2026-09-07: "active, inactive, deleted"), not a row that vanished.
        gone = Partner.objects.create(name="Gone Directory Partner", active_status=False)
        gone.soft_delete()

        for principal in (self.admin, self.cd):
            self.client.force_login(principal)
            response = self.client.get("/admin-panel/users")
            self.assertEqual(response.status_code, 200)
            self.assertContains(response, "Partner Organisations")
            self.assertContains(response, "Visible Directory Partner")
            self.assertContains(response, "Gone Directory Partner")
            self.assertContains(response, ">Deleted<")
            self.assertContains(response, ">Active<")
            self.assertNotContains(response, 'aria-label="Activate Gone Directory Partner"')
            self.assertContains(response, "Add Partner")
            # Two actions per row (owner, 2026-09-07): the lifecycle toggle,
            # and — for the Admin alone — permanent deletion. The soft
            # "Remove" button is gone from the page.
            # The fixture is active (the model default), so its toggle reads
            # Deactivate; a freshly onboarded one reads Activate — covered by
            # PartnerLifecycleTests.
            self.assertContains(response, "Deactivate")
            self.assertNotContains(response, "Remove Partner")
            # The organisation's name opens its profile.
            self.assertContains(response, '<a href="/partners/')

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


class PartnerLifecycleTests(TestCase):
    """Activate / deactivate / delete, and the roster (owner, 2026-09-07).

    "When it has just been added, the button should be activate, and once the
    partner has been added, it should be deactivated. Delete … is to delete the
    partner permanently and that should only be done by the admin."
    """

    def setUp(self):
        User = get_user_model()
        self.admin = User.objects.create_user(
            email="lifecycle-admin@edify.test", name="Lifecycle Admin",
            roles=[EdifyRole.ADMIN.value], active_role=EdifyRole.ADMIN.value,
            password="StrongPassphrase!23",
        )
        self.cd = User.objects.create_user(
            email="lifecycle-cd@edify.test", name="Lifecycle CD",
            roles=[EdifyRole.COUNTRY_DIRECTOR.value],
            active_role=EdifyRole.COUNTRY_DIRECTOR.value,
            password="StrongPassphrase!23",
        )
        self.hr = User.objects.create_user(
            email="lifecycle-hr@edify.test", name="Lifecycle HR",
            roles=[EdifyRole.HUMAN_RESOURCES.value],
            active_role=EdifyRole.HUMAN_RESOURCES.value,
            password="StrongPassphrase!23",
        )

    def test_a_new_organisation_starts_inactive(self):
        created = onboard({"name": "Fresh Partner", "expertiseAreas": "Literacy, EdTech"}, self.cd)
        partner = Partner.objects.get(id=created["id"])
        self.assertFalse(partner.active_status)
        self.assertEqual(partner.expertise_areas, ["Literacy", "EdTech"])

    def test_the_toggle_activates_then_deactivates_and_is_audited(self):
        from apps.audit.models import AuditLog

        partner = Partner.objects.create(name="Toggle Partner", active_status=False)
        set_partner_status(partner.id, True, self.cd)
        partner.refresh_from_db()
        self.assertTrue(partner.active_status)
        set_partner_status(partner.id, False, self.admin)
        partner.refresh_from_db()
        self.assertFalse(partner.active_status)
        actions = set(
            AuditLog.objects.filter(subject_id=partner.id).values_list("action", flat=True)
        )
        self.assertIn("partner.activated", actions)
        self.assertIn("partner.deactivated", actions)

    def test_only_admin_may_purge_and_only_without_history(self):
        from apps.partners.models import PartnerAssignment
        from apps.schools.models import School

        clean = Partner.objects.create(name="Never Used Partner", active_status=False)
        with self.assertRaises(Forbidden):
            purge_partner(clean.id, self.cd)
        self.assertTrue(Partner.objects.filter(id=clean.id).exists())

        purge_partner(clean.id, self.admin)
        self.assertFalse(Partner.all_objects.filter(id=clean.id).exists())

        worked = Partner.objects.create(name="Worked Partner", active_status=True)
        school = School.objects.create(name="Roster School", school_id="RS-001")
        PartnerAssignment.objects.create(partner=worked, school=school)
        with self.assertRaises(ConflictError):
            purge_partner(worked.id, self.admin)
        self.assertTrue(Partner.objects.filter(id=worked.id).exists())

    def test_the_users_page_toggles_and_purges_by_role(self):
        partner = Partner.objects.create(name="Page Partner", active_status=False)

        self.client.force_login(self.cd)
        self.client.post(
            "/admin-panel/users", {"action": "activate_partner", "partner_id": partner.id}
        )
        partner.refresh_from_db()
        self.assertTrue(partner.active_status)

        # A Country Director cannot delete permanently.
        self.client.post(
            "/admin-panel/users", {"action": "purge_partner", "partner_id": partner.id}
        )
        self.assertTrue(Partner.all_objects.filter(id=partner.id).exists())
        response = self.client.get("/admin-panel/users")
        self.assertContains(response, "Deactivate")
        self.assertNotContains(response, "Delete Permanently")

        self.client.force_login(self.admin)
        response = self.client.get("/admin-panel/users")
        self.assertContains(response, "Delete Permanently")
        self.client.post(
            "/admin-panel/users", {"action": "purge_partner", "partner_id": partner.id}
        )
        self.assertFalse(Partner.all_objects.filter(id=partner.id).exists())

    def test_the_roster_is_scoped_and_removable(self):
        partner = Partner.objects.create(name="Roster Partner", active_status=True)
        member = add_member(
            partner.id,
            {"name": "Grace Nakato", "role": "volunteer", "phone": "0700"},
            self.cd,
        )
        self.assertEqual(member.role, "volunteer")
        with self.assertRaises(Forbidden):
            add_member(partner.id, {"name": "Blocked"}, self.hr)
        remove_member(partner.id, member.id, self.admin)
        self.assertEqual(partner.members.count(), 0)

    def test_the_profile_shows_history_roster_and_counts(self):
        from apps.activities.models import Activity
        from apps.schools.models import School

        partner = Partner.objects.create(name="Profiled Partner", active_status=True)
        school = School.objects.create(name="History School", school_id="HS-001")
        Activity.objects.create(
            activity_type="training", status="completed", school=school,
            assigned_partner_id=partner.id, delivery_contact_name="Grace Nakato",
        )
        Activity.objects.create(
            activity_type="school_visit", status="assigned_to_partner", school=school,
            assigned_partner_id=partner.id,
        )
        Activity.objects.create(
            activity_type="school_visit", status="cancelled", school=school,
            assigned_partner_id=partner.id,
        )
        add_member(partner.id, {"name": "Paul Okello", "role": "staff"}, self.cd)

        self.client.force_login(self.cd)
        response = self.client.get(f"/partners/{partner.id}")
        self.assertEqual(response.status_code, 200)
        counts = response.context["counts"]
        self.assertEqual(counts, {"completed": 1, "assigned": 1, "incomplete": 1})
        self.assertContains(response, "Staff and volunteers")
        self.assertContains(response, "Paul Okello")
        # Named on a delivery but not on the roster — surfaced, not lost.
        self.assertContains(response, "Grace Nakato")
        self.assertContains(response, "Activity history")
        self.assertContains(response, f'href="/schools/{school.id}"')


class PartnerSupportedSchoolsAndBioTests(TestCase):
    """The schools a partner supports, with performance; and the partner's own
    hand on its bio (owner, 2026-09-07).
    """

    def setUp(self):
        from datetime import datetime, timezone as dt_tz

        from apps.activities.models import Activity
        from apps.schools.models import School
        from apps.ssa.models import SsaRecord

        User = get_user_model()
        self.cd = User.objects.create_user(
            email="support-cd@edify.test", name="Support CD",
            roles=[EdifyRole.COUNTRY_DIRECTOR.value],
            active_role=EdifyRole.COUNTRY_DIRECTOR.value, password="StrongPassphrase!23",
        )
        self.partner_user = User.objects.create_user(
            email="own-org@partner.test", name="Own Org Login",
            roles=[EdifyRole.PARTNER_ADMIN.value], active_role=EdifyRole.PARTNER_ADMIN.value,
            password="StrongPassphrase!23",
        )
        self.partner = Partner.objects.create(
            name="Supporting Partner", active_status=True, region_name="Central",
            user=self.partner_user,
        )
        self.other = Partner.objects.create(name="Other Partner", active_status=True)
        self.school = School.objects.create(name="Supported School", school_id="SUP-001")
        Activity.objects.create(
            activity_type="school_visit", status="completed", school=self.school,
            assigned_partner_id=self.partner.id,
        )
        Activity.objects.create(
            activity_type="school_visit", status="assigned_to_partner", school=self.school,
            assigned_partner_id=self.partner.id,
        )
        Activity.objects.create(
            activity_type="training", status="completed", school=self.school,
            assigned_partner_id=self.partner.id,
        )
        SsaRecord.objects.create(
            school=self.school, fy="2025", average_score=5.0,
            date_of_ssa=datetime(2025, 3, 1, tzinfo=dt_tz.utc), verification_status="confirmed",
        )
        SsaRecord.objects.create(
            school=self.school, fy="2026", average_score=6.5,
            date_of_ssa=datetime(2026, 3, 1, tzinfo=dt_tz.utc), verification_status="confirmed",
        )

    def test_the_profile_lists_supported_schools_with_counts_and_performance(self):
        self.client.force_login(self.cd)
        response = self.client.get(f"/partners/{self.partner.id}")
        self.assertEqual(response.status_code, 200)
        rows = response.context["supported_schools"]
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["school"].id, self.school.id)
        self.assertEqual((row["visits_done"], row["visits"]), (1, 2))
        self.assertEqual((row["trainings_done"], row["trainings"]), (1, 1))
        # Latest confirmed SSA, and the move since the one before it.
        self.assertEqual(row["score"], 6.5)
        self.assertEqual(row["delta"], 1.5)
        self.assertContains(response, "Schools supported")
        self.assertContains(response, f'href="/schools/{self.school.id}"')

    def test_the_partner_edits_its_own_bio_but_not_its_region(self):
        self.client.force_login(self.partner_user)
        response = self.client.get(f"/partners/{self.partner.id}/edit-drawer")
        self.assertEqual(response.status_code, 200)
        # Region and intervention are Edify's call: shown, not editable.
        self.assertNotContains(response, 'name="region_name"')
        self.assertContains(response, "set by Edify")

        response = self.client.post(
            f"/partners/{self.partner.id}/edit-drawer",
            {"contact_person": "Grace N", "phone": "0700 111 222", "email": "grace@partner.test",
             "expertise": "Literacy, Numeracy", "notes": "Works in Wakiso",
             "region_name": "Northern", "name": "Renamed By Partner"},
        )
        self.assertEqual(response.status_code, 200)
        self.partner.refresh_from_db()
        self.assertEqual(self.partner.contact_person, "Grace N")
        self.assertEqual(self.partner.expertise_areas, ["Literacy", "Numeracy"])
        self.assertEqual(self.partner.region_name, "Central")
        self.assertEqual(self.partner.name, "Supporting Partner")

        # Another organisation's drawer is not theirs to open.
        response = self.client.get(f"/partners/{self.other.id}/edit-drawer")
        self.assertEqual(response.status_code, 403)

    def test_the_country_director_edits_region_and_name(self):
        self.client.force_login(self.cd)
        response = self.client.get(f"/partners/{self.partner.id}/edit-drawer")
        self.assertContains(response, 'name="region_name"')
        response = self.client.post(
            f"/partners/{self.partner.id}/edit-drawer",
            {"name": "Supporting Partner Ltd", "region_name": "Northern",
             "ssa_intervention": "christlike_behaviour", "contact_person": "Grace N",
             "phone": "", "email": "", "expertise": "", "notes": ""},
        )
        self.assertEqual(response.status_code, 200)
        self.partner.refresh_from_db()
        self.assertEqual(self.partner.name, "Supporting Partner Ltd")
        self.assertEqual(self.partner.region_name, "Northern")
        self.assertEqual(self.partner.ssa_intervention, "christlike_behaviour")
