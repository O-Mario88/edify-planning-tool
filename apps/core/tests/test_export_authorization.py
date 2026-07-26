"""Bulk extraction is its own permission, on every route that performs it.

A page permission says "you may look at this". `data.export` says "you may
take a copy of it away". They are different questions: a Partner Field Officer
can legitimately read their own assignments, and should still not be able to
pull a CSV of them out of the system.

An earlier audit found `data.export` enforced by exactly one of roughly twenty
export endpoints — every other page permission implicitly granted bulk
extraction — and added `require_export_permission`. That audit also drew the
line deliberately, and this test encodes where:

    org-wide registers  → require data.export
    your own records    → page permission is enough

"Extraction of what you already see is not the risk; the org register is." So
a Partner Field Officer downloading their own targets is fine, and the same
officer downloading the partner register is not.

Asserted by behaviour rather than by counting decorators, because the failure
mode is not a missing decorator today — it is the org-wide export someone adds
next quarter without one, or an own-data exemption quietly widened to cover a
dataset that is not your own.
"""

from __future__ import annotations

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import get_resolver

from apps.accounts.models import StaffProfile
from apps.core.rbac import EdifyRole, Permission, permissions_for_role

# Help-centre exports are documentation, not organisational data: they render
# the same guidance the pages already show to whoever can read them.
NOT_ORGANISATIONAL_DATA = ("/help/export",)

# Exports of the signed-in user's OWN records. Page permission is the whole
# control here by design. Listed one by one rather than matched on a "/my-"
# prefix, so adding a route to this exemption is a deliberate edit somebody
# has to justify in review.
OWN_DATA_EXPORTS = frozenset(
    {
        "/my-targets/export",
        "/my-professional-development/export",
    }
)


def _export_routes() -> list[str]:
    """Every argument-free route whose path advertises an export."""

    def walk(resolver, prefix=""):
        for pattern in resolver.url_patterns:
            path = prefix + str(pattern.pattern)
            if hasattr(pattern, "url_patterns"):
                yield from walk(pattern, path)
            else:
                yield path

    routes = set()
    for path in walk(get_resolver()):
        if "export" not in path.lower():
            continue
        if "<" in path or "(?P" in path:
            continue
        url = "/" + path
        if url.startswith(NOT_ORGANISATIONAL_DATA):
            continue
        routes.add(url)
    return sorted(routes)


def _roles_without_export() -> list[str]:
    return [
        role
        for role in EdifyRole.values()
        if Permission.EXPORT.value not in permissions_for_role(role)
    ]


class ExportPermissionTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.routes = _export_routes()
        cls.denied_roles = _roles_without_export()
        User = get_user_model()
        cls.users = {}
        for role in cls.denied_roles:
            slug = role.lower().replace(" ", "-")
            user = User.objects.create_user(
                email=f"export-{slug}@edify.test",
                password="password123",
                name=f"Export {role}",
                roles=[role],
                active_role=role,
                is_active=True,
            )
            StaffProfile.objects.create(user=user, title=role)
            cls.users[role] = user

    def test_there_are_export_routes_to_check(self):
        """A guard over an empty list passes and means nothing."""
        self.assertGreaterEqual(len(self.routes), 5, self.routes)

    def test_some_roles_genuinely_lack_the_permission(self):
        """If every role could export, this whole test would be vacuous."""
        self.assertGreaterEqual(len(self.denied_roles), 1, self.denied_roles)

    def _served_a_download(self, client, url) -> bool:
        """Did bytes actually leave? The sharpest form of the question."""
        response = client.get(url)
        return response.status_code == 200 and "attachment" in response.headers.get(
            "Content-Disposition", ""
        )

    def test_no_org_wide_export_reaches_a_role_without_the_permission(self):
        org_wide = [url for url in self.routes if url not in OWN_DATA_EXPORTS]
        self.assertGreaterEqual(len(org_wide), 4, org_wide)
        for role in self.denied_roles:
            client = Client()
            client.force_login(self.users[role])
            for url in org_wide:
                with self.subTest(role=role, url=url):
                    self.assertFalse(
                        self._served_a_download(client, url),
                        f"{role} was served {url} without data.export — a page "
                        "permission alone is granting bulk extraction of an "
                        "organisation-wide dataset.",
                    )

    def test_the_own_data_exemptions_still_exist(self):
        """If these stopped being reachable the exemption list would be stale,
        and a stale exemption list makes the test above quietly narrower."""
        stale = [url for url in OWN_DATA_EXPORTS if url not in self.routes]
        self.assertEqual(stale, [], f"exempted routes that no longer exist: {stale}")

    def test_own_data_export_is_deliberately_open(self):
        """Pins the policy itself, so narrowing it is a visible decision rather
        than a silently failing test somewhere else."""
        client = Client()
        client.force_login(self.users[EdifyRole.CCEO.value])
        self.assertTrue(
            self._served_a_download(client, "/my-targets/export"),
            "a CCEO exporting their own targets is intended to work",
        )
