"""Partners service tests — ownership/scope check on update()."""

from django.contrib.auth import get_user_model
from django.test import TestCase

from apps.core.exceptions import Forbidden
from apps.partners.models import Partner
from apps.partners.services import update


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
        self.assertEqual(self.partner.name, "Target Partner")
