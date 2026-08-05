"""The school directory export honours `data.export` like every other export.

`require_export_permission` exists because an earlier audit found `data.export`
enforced by exactly one of ~20 export endpoints. Nine view modules were fixed.
`school_directory_view` was not, and it is the largest export in the product —
since the 5,000-row cap was removed it returns all 16,274 schools.

Measured on live production before this change: signed in as a CCEO, who holds
neither `Permission.EXPORT` nor `RolePermissionService.can_export`,
`/schools?export=csv` returned **200 with 824 rows of CSV**. Both the
permission and the gate said no; the view never asked either of them.

The data was correctly scoped — 824 was exactly that CCEO's own portfolio — so
this was never a cross-scope leak. It was the export permission not existing in
practice on the one page where bulk extraction matters most.

This is a capability change, not only a hardening: a CCEO who exports their
school list today will start seeing the access-denied page. That follows the
RBAC matrix, which deliberately withholds `data.export` from the CCEO role. If
CCEOs are meant to export, the fix belongs in the matrix rather than in this
view being the single exception to it.
"""

from __future__ import annotations

from django.contrib.auth import get_user_model
from django.contrib.messages.middleware import MessageMiddleware
from django.contrib.sessions.middleware import SessionMiddleware
from django.test import RequestFactory, TestCase

from apps.core.permissions import RolePermissionService
from apps.frontend.views.school_views import school_directory_view

User = get_user_model()


class SchoolExportHonoursExportPermissionTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.cceo = User.objects.create(
            id="xp-cceo",
            email="xp-cceo@edify.org",
            name="XP Field Officer",
            roles=["CCEO"],
            active_role="CCEO",
            is_active=True,
        )
        cls.pl = User.objects.create(
            id="xp-pl",
            email="xp-pl@edify.org",
            name="XP Lead",
            roles=["Program Lead"],
            active_role="Program Lead",
            is_active=True,
        )

    def _get(self, user, path):
        request = RequestFactory().get(path)
        SessionMiddleware(lambda r: None).process_request(request)
        MessageMiddleware(lambda r: None).process_request(request)
        request.user = user
        return school_directory_view(request)

    def test_the_fixture_matches_the_permission_matrix(self):
        # Guards the guard: if the matrix ever grants the CCEO data.export,
        # the assertions below stop meaning anything and should be revisited
        # rather than silently passing.
        self.assertFalse(RolePermissionService.can_export(self.cceo, "/schools"))
        self.assertTrue(RolePermissionService.can_export(self.pl, "/schools"))

    def test_a_role_without_export_permission_gets_no_csv(self):
        response = self._get(self.cceo, "/schools?export=csv")
        self.assertNotEqual(
            response.get("Content-Type", ""),
            "text/csv",
            "a role without data.export must not receive a spreadsheet",
        )

    def test_the_xlsx_route_is_gated_too(self):
        """Same view, different query value — the gate reads `export`, not the
        format, so both have to be covered or one becomes the way round."""
        response = self._get(self.cceo, "/schools?export=xlsx")
        self.assertNotIn("spreadsheet", response.get("Content-Type", ""))

    def test_a_role_with_export_permission_still_gets_the_csv(self):
        response = self._get(self.pl, "/schools?export=csv")
        self.assertEqual(response.get("Content-Type", ""), "text/csv")

    def test_the_ordinary_page_still_loads_for_a_role_without_export(self):
        """The gate is about extraction, not about seeing the directory."""
        response = self._get(self.cceo, "/schools")
        self.assertEqual(response.status_code, 200)
        self.assertIn("text/html", response.get("Content-Type", ""))
