"""A scope that fails to compute must say so.

Two branches of `build_user_scope` wrapped their whole computation in
`except Exception: pass` — the Project Coordinator's and the Partner's. If
anything inside raised, the user fell through to an empty scope: no schools, no
districts, no projects. The page then rendered HTTP 200 showing nothing, which
is exactly what a coordinator who genuinely manages nothing sees. No error, no
log, no way to tell the two apart.

The fall-through itself is defensible — an empty scope shows no data, which
beats showing the wrong data. The silence was not.
"""

from __future__ import annotations

import logging
from unittest import mock

from django.test import TestCase

from apps.accounts.models import StaffProfile, User
from apps.core.rbac import EdifyRole
from apps.core.scoping import resolve_user_scope

SCOPING_LOGGER = "apps.core.scoping"


def _principal(role: str):
    user = User.objects.create_user(
        email=f"scope-{role.lower().replace(' ', '-')}@edify.test",
        password="password123",
        name="Scope Tester",
        roles=[role],
        active_role=role,
        is_active=True,
    )
    StaffProfile.objects.create(user=user, title=role)
    return user


class ScopeFailureIsVisibleTest(TestCase):
    def test_a_coordinator_scope_failure_is_logged(self):
        user = _principal(EdifyRole.PROJECT_COORDINATOR.value)
        with mock.patch(
            "apps.projects.models.Project.objects.filter",
            side_effect=RuntimeError("projects table unavailable"),
        ):
            with self.assertLogs(SCOPING_LOGGER, level=logging.ERROR) as logs:
                scope = resolve_user_scope(user)
        joined = "\n".join(logs.output)
        self.assertIn("Project Coordinator scope computation failed", joined)
        self.assertIn("projects table unavailable", joined)
        # And the caller still gets a usable, empty scope rather than a crash.
        self.assertEqual(list(scope.school_ids or []), [])

    def test_a_partner_scope_failure_is_logged(self):
        user = _principal(EdifyRole.PARTNER_ADMIN.value)
        with (
            mock.patch(
                "apps.core.scoping.resolve_partner_ids", return_value=["partner-1"]
            ),
            mock.patch(
                "apps.partners.models.PartnerAssignment.objects.filter",
                side_effect=RuntimeError("assignments unavailable"),
            ),
        ):
            with self.assertLogs(SCOPING_LOGGER, level=logging.ERROR) as logs:
                resolve_user_scope(user)
        self.assertIn("Partner scope computation failed", "\n".join(logs.output))

    def test_a_healthy_scope_logs_nothing(self):
        """The log has to stay quiet when nothing is wrong, or it becomes
        noise nobody reads — which is the state it was replacing."""
        user = _principal(EdifyRole.PROJECT_COORDINATOR.value)
        with self.assertNoLogs(SCOPING_LOGGER, level=logging.ERROR):
            resolve_user_scope(user)
