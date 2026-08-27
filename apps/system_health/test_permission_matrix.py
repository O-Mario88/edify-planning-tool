"""The role x surface matrix must be the truth, not a second copy of it.

The mandate's §45.5 deliverable was recorded as not built and deferred twice.
The reason it is worth building is SEC-01: the school edit drawer gated its
WRITE on the READ helper, and a coverage matrix assembled from a hand-written
model of the rules would have agreed with the bug. So the matrix asks the same
functions the request path asks, and these tests hold it to that.

The mirror that is not a call is the one line of `RequirePermissions`
semantics, and the first version of this module got it wrong — all-of where the
guard is any-of — which produced five API routes reported as reachable by
nobody. A finding it had invented. `test_any_of_semantics_match_the_real_guard`
exists so that cannot happen again quietly.
"""

from __future__ import annotations

from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

from apps.core.rbac import EdifyRole
from apps.system_health.permission_matrix import (
    _RolePrincipal,
    build_permission_matrix,
    matrix_as_json,
    matrix_as_markdown,
)

DOCS = Path(settings.BASE_DIR) / "docs"
JSON_PATH = DOCS / "platform-permission-matrix.json"
MARKDOWN_PATH = DOCS / "platform-permission-matrix.md"

#: Measured. Held as a floor, not a target: the count may grow with new
#: surfaces, and a DROP means a route lost its declared authority, which is the
#: SEC-01 shape and must be looked at.
MIN_GUARDED_ROUTES = 845


class MatrixMatchesTheLiveSourceTest(SimpleTestCase):
    def setUp(self):
        self.matrix = build_permission_matrix()

    def test_the_checked_in_matrix_is_current(self):
        self.assertEqual(
            JSON_PATH.read_text(encoding="utf-8"),
            matrix_as_json(self.matrix),
            "docs/platform-permission-matrix.json is stale; run "
            "manage.py build_permission_matrix",
        )

    def test_the_readable_matrix_is_current(self):
        self.assertEqual(
            MARKDOWN_PATH.read_text(encoding="utf-8"),
            matrix_as_markdown(self.matrix),
            "docs/platform-permission-matrix.md is stale; run "
            "manage.py build_permission_matrix",
        )

    def test_it_covers_every_route_in_the_resolver(self):
        summary = self.matrix["summary"]
        self.assertEqual(
            summary["routes_total"],
            summary["routes_guarded"] + summary["routes_unguarded"],
            "every routed surface is either guarded or listed as unguarded — "
            "a matrix that silently dropped what it could not classify would "
            "be a coverage percentage rather than a coverage report",
        )
        self.assertGreater(summary["routes_total"], 1000)

    def test_no_guarded_surface_has_lost_its_authority(self):
        self.assertGreaterEqual(
            self.matrix["summary"]["routes_guarded"],
            MIN_GUARDED_ROUTES,
            "fewer routes declare an authority than when this was measured. "
            "Either a surface was retired, or one lost its gate — the second "
            "is SEC-01 and is why this floor exists.",
        )

    def test_every_role_appears_and_none_is_stranded(self):
        roles = set(self.matrix["roles"])
        self.assertEqual(roles, {r.value for r in EdifyRole})
        for role, count in self.matrix["routes_reachable_by_role"].items():
            with self.subTest(role):
                self.assertGreater(
                    count,
                    0,
                    f"{role} can reach no guarded surface at all, which means "
                    "either the role is unused or its permissions are "
                    "mis-declared",
                )

    def test_no_guarded_surface_is_reachable_by_nobody(self):
        self.assertEqual(
            self.matrix["unreachable_guarded_routes"],
            [],
            "a guarded surface no role can reach is either a retired page or "
            "a mis-declared permission key; either way nobody can use it",
        )


class TheMatrixAsksTheRealGatesTest(SimpleTestCase):
    """The guards against this becoming a second definition of the rules."""

    def test_any_of_semantics_match_the_real_guard(self):
        """One line of RequirePermissions is mirrored; hold it to the original.

        Driven through the actual permission class with a stand-in request and
        view, so a change from any-of to all-of fails here rather than silently
        changing what the published matrix claims.
        """
        from apps.core.permissions import RequirePermissions

        class _View:
            required_permissions = ["evidence.review", "payment.act"]

        class _Request:
            def __init__(self, role):
                self.user = _RolePrincipal(role)

        gate = RequirePermissions()
        cceo = _Request(EdifyRole.CCEO.value)
        # A CCEO holds planning permissions but not payment.act; under any-of
        # they pass if they hold EITHER named permission.
        from apps.core.permissions import has_permission

        holds_some = any(
            has_permission(cceo.user, p) for p in _View.required_permissions
        )
        self.assertEqual(
            gate.has_permission(cceo, _View),
            holds_some,
            "RequirePermissions is any-of; the matrix mirrors that one line "
            "and must not drift from it",
        )

    def test_the_page_gate_is_the_one_the_request_path_uses(self):
        from apps.core.permissions import RolePermissionService

        matrix = build_permission_matrix()
        checked = 0
        for row in matrix["guarded"]:
            key = row["page_permission"]
            if not key:
                continue
            for role in matrix["roles"]:
                expected = RolePermissionService.can_view_page(
                    _RolePrincipal(role), key
                )
                self.assertEqual(
                    role in row["roles"],
                    expected,
                    f"{role} vs {row['route']} disagrees with can_view_page",
                )
            checked += 1
            if checked >= 40:
                break
        self.assertGreater(checked, 0)

    def test_an_unauthenticated_caller_passes_nothing(self):
        from apps.core.permissions import RolePermissionService

        class _Anonymous:
            is_authenticated = False
            active_role = None

        self.assertFalse(RolePermissionService.can_view_page(_Anonymous(), "dashboard"))
