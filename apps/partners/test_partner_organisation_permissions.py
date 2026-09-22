"""Partner organisations versus partner logins (owner, 2026-09-15).

Admin, the Country Director and Impact Assessment add partner organisations.
Only user administrators (Admin, Country Director) create, invite or link the
accounts partner staff sign in with. Creating an organisation never creates an
account, whoever creates it — Impact Assessment must have no indirect path to
user administration.
"""

from __future__ import annotations

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings

from apps.audit.models import AuditLog
from apps.core.exceptions import Forbidden
from apps.core.permissions import has_permission
from apps.core.rbac import EdifyRole, Permission
from apps.notifications.models import Notification
from apps.partners.models import Partner, PartnerUserSetupStatus
from apps.partners.services import configure_partner_user, onboard

User = get_user_model()
PASSWORD = "StrongPassphrase!23"


def _user(email: str, role: str) -> User:
    return User.objects.create_user(
        email=email,
        name=email.split("@")[0].title(),
        roles=[role],
        active_role=role,
        password=PASSWORD,
    )


@override_settings(ALLOWED_HOSTS=["testserver", "localhost"])
class PartnerOrganisationPermissionTests(TestCase):
    def setUp(self):
        self.admin = _user("org-admin@edify.test", EdifyRole.ADMIN.value)
        self.cd = _user("org-cd@edify.test", EdifyRole.COUNTRY_DIRECTOR.value)
        self.ia = _user("org-ia@edify.test", EdifyRole.IMPACT_ASSESSMENT.value)
        self.pl = _user("org-pl@edify.test", EdifyRole.COUNTRY_PROGRAM_LEAD.value)
        self.hr = _user("org-hr@edify.test", EdifyRole.HUMAN_RESOURCES.value)
        self.field_officer = _user(
            "org-pfo@edify.test", EdifyRole.PARTNER_FIELD_OFFICER.value
        )

    # ── The permission matrix ────────────────────────────────────────────
    def test_the_matrix_separates_organisations_from_logins(self):
        create = Permission.PARTNER_ORGANISATION_CREATE.value
        users = Permission.PARTNER_USER_MANAGE.value
        for principal in (self.admin, self.cd, self.ia):
            with self.subTest(role=principal.active_role):
                self.assertTrue(has_permission(principal, create))
        for principal in (self.pl, self.hr, self.field_officer):
            with self.subTest(role=principal.active_role):
                self.assertFalse(has_permission(principal, create))
        self.assertTrue(has_permission(self.admin, users))
        self.assertTrue(has_permission(self.cd, users))
        for permission in (
            users,
            Permission.USER_MANAGE.value,
            Permission.PARTNER_MANAGE.value,
        ):
            with self.subTest(permission=permission):
                self.assertFalse(has_permission(self.ia, permission))

    # ── Creating an organisation ─────────────────────────────────────────
    def test_admin_cd_and_ia_each_add_an_organisation(self):
        for principal in (self.admin, self.cd, self.ia):
            with self.subTest(role=principal.active_role):
                created = onboard(
                    {"name": f"Org by {principal.active_role}"}, principal
                )
                partner = Partner.objects.get(id=created["id"])
                self.assertFalse(partner.active_status)
                self.assertEqual(
                    partner.user_setup_status, PartnerUserSetupStatus.PENDING
                )

    def test_program_lead_hr_and_partner_field_officer_cannot(self):
        for principal in (self.pl, self.hr, self.field_officer):
            with self.subTest(role=principal.active_role):
                with self.assertRaises(Forbidden):
                    onboard({"name": f"Blocked {principal.active_role}"}, principal)
        self.assertFalse(Partner.objects.filter(name__startswith="Blocked").exists())

    def test_an_email_on_the_form_creates_no_account_for_anyone(self):
        """The old onboarding minted an active PartnerAdmin login from the
        email field. For IA that was user creation by another name."""
        for principal, email in (
            (self.ia, "ia-made@partner.test"),
            (self.cd, "cd-made@partner.test"),
        ):
            with self.subTest(role=principal.active_role):
                created = onboard(
                    {"name": f"Emailed {principal.active_role}", "email": email},
                    principal,
                )
                self.assertFalse(User.objects.filter(email=email).exists())
                partner = Partner.objects.get(id=created["id"])
                self.assertIsNone(partner.user_id)
                self.assertEqual(partner.email, email)

    def test_creation_is_audited_with_the_actor_and_new_value(self):
        created = onboard({"name": "Audited Org"}, self.ia)
        row = AuditLog.objects.get(action="partner.created", subject_id=created["id"])
        self.assertEqual(row.actor_id, self.ia.id)
        self.assertEqual(row.actor_role, EdifyRole.IMPACT_ASSESSMENT.value)
        self.assertIsNone(row.payload["previous"])
        self.assertEqual(row.payload["new"]["name"], "Audited Org")
        self.assertEqual(row.payload["new"]["userSetupStatus"], "pending")

    def test_ia_creation_tells_the_user_administrators(self):
        with self.captureOnCommitCallbacks(execute=True):
            created = onboard({"name": "Needs Logins"}, self.ia)
        recipients = set(
            Notification.objects.filter(
                source_event_type="partner_user_setup_required",
                context_id=created["id"],
            ).values_list("recipient_id", flat=True)
        )
        self.assertEqual(recipients, {self.admin.id, self.cd.id})
        self.assertNotIn(self.ia.id, recipients)

    # ── Logins stay with user administration ─────────────────────────────
    def test_ia_cannot_configure_a_partner_login(self):
        partner = Partner.objects.create(name="No Login Yet")
        for mode in ("invite", "link", "not_required"):
            with self.subTest(mode=mode):
                with self.assertRaises(Forbidden):
                    configure_partner_user(
                        partner.id,
                        {"mode": mode, "email": "sneaky@partner.test"},
                        self.ia,
                    )
        self.assertFalse(User.objects.filter(email="sneaky@partner.test").exists())

    def test_a_user_administrator_invites_and_the_condition_closes(self):
        with self.captureOnCommitCallbacks(execute=True):
            created = onboard({"name": "Invite Me"}, self.ia)
        result = configure_partner_user(
            created["id"],
            {"mode": "invite", "email": "lead@invite-me.test", "name": "Lead"},
            self.cd,
        )
        self.assertEqual(result["userSetupStatus"], "configured")
        login = User.objects.get(email="lead@invite-me.test")
        self.assertEqual(login.roles, [EdifyRole.PARTNER_ADMIN.value])
        self.assertEqual(login.status, "pending_invited")
        self.assertEqual(Partner.objects.get(id=created["id"]).user_id, login.id)
        self.assertTrue(
            AuditLog.objects.filter(
                action="partner.user_setup_changed", subject_id=created["id"]
            ).exists()
        )
        self.assertFalse(
            Notification.objects.filter(
                source_event_type="partner_user_setup_required",
                context_id=created["id"],
                resolved_at__isnull=True,
            ).exists()
        )

    def test_only_partner_accounts_can_be_linked(self):
        partner = Partner.objects.create(name="Link Target")
        with self.assertRaises(Exception):
            configure_partner_user(
                partner.id, {"mode": "link", "email": self.pl.email}, self.admin
            )
        configure_partner_user(
            partner.id, {"mode": "link", "email": self.field_officer.email}, self.admin
        )
        self.assertEqual(
            Partner.objects.get(id=partner.id).user_id, self.field_officer.id
        )

    # ── Direct URLs and the API ──────────────────────────────────────────
    def test_ia_is_refused_the_users_page_and_the_user_apis(self):
        self.client.force_login(self.ia)
        # A plain page GET is refused the platform's controlled way: back to
        # the dashboard with the reason (render_access_denied).
        page = self.client.get("/admin-panel/users")
        self.assertRedirects(page, "/dashboard", fetch_redirect_response=False)
        self.assertEqual(
            self.client.get("/admin-panel/users", HTTP_HX_REQUEST="true").status_code,
            403,
        )
        before = User.objects.count()
        response = self.client.post(
            "/admin-panel/users",
            {
                "action": "create",
                "email": "ia-user@edify.test",
                "name": "Ia Made",
                "role": EdifyRole.CCEO.value,
            },
        )
        self.assertIn(response.status_code, (302, 403))
        self.assertEqual(User.objects.count(), before)
        api = self.client.post(
            "/api/admin/users",
            {"email": "ia-api@edify.test", "name": "Api", "role": "CCEO"},
            content_type="application/json",
        )
        self.assertIn(api.status_code, (401, 403, 404, 405))
        self.assertFalse(User.objects.filter(email="ia-api@edify.test").exists())
        partner = Partner.objects.create(name="Api Setup Target")
        setup = self.client.post(
            f"/api/partners/{partner.id}/user-setup",
            {"mode": "invite", "email": "ia-invite@edify.test"},
            content_type="application/json",
        )
        self.assertIn(setup.status_code, (401, 403))
        self.assertEqual(
            self.client.get(f"/partners/{partner.id}/user-setup").status_code, 403
        )
        self.assertFalse(User.objects.filter(email="ia-invite@edify.test").exists())

    def test_ia_adds_an_organisation_from_partner_oversight(self):
        self.client.force_login(self.ia)
        page = self.client.get("/partner-oversight/")
        self.assertContains(page, "Add Partner Organisation")
        drawer = self.client.get("/partners/create", HTTP_HX_REQUEST="true")
        self.assertContains(drawer, "No sign-in account is created here")
        # Interventions arrive as ticks, and an organisation may do more than
        # one of them (owner, 2026-09-22).
        response = self.client.post(
            "/partners/create",
            {
                "name": "Browser Org",
                "ssa_interventions": ["christlike_behaviour", "financial_health"],
            },
            HTTP_HX_REQUEST="true",
        )
        partner = Partner.objects.get(name="Browser Org")
        self.assertContains(response, f"/partners/{partner.id}")
        self.assertIsNone(partner.user_id)
        self.assertEqual(
            partner.ssa_interventions,
            ["christlike_behaviour", "financial_health"],
        )
        self.assertEqual(partner.ssa_intervention, "christlike_behaviour")

    def test_the_program_lead_is_offered_no_create_door(self):
        self.client.force_login(self.pl)
        page = self.client.get("/partner-oversight/")
        self.assertNotContains(page, "Add Partner Organisation")
        self.assertEqual(
            self.client.post(
                "/partners/create", {"name": "PL Org"}, HTTP_HX_REQUEST="true"
            ).status_code,
            403,
        )
        self.assertFalse(Partner.objects.filter(name="PL Org").exists())

    def test_the_accountant_reads_but_does_not_edit_an_organisation(self):
        accountant = _user("org-acc@edify.test", EdifyRole.PROGRAM_ACCOUNTANT.value)
        partner = Partner.objects.create(name="Read Only Org")
        self.client.force_login(accountant)
        self.assertEqual(
            self.client.get(f"/partners/{partner.id}/edit-drawer").status_code, 403
        )
        self.client.force_login(self.ia)
        self.assertEqual(
            self.client.get(f"/partners/{partner.id}/edit-drawer").status_code, 200
        )
