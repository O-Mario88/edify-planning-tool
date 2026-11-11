"""The Go gateway reads the same role → permission matrix as this application.

Go owns permission checks for what has moved to it (owner brief, 2026-11-11);
it embeds platform/backend/internal/rbac/role_permissions.json. This test
fails the moment apps.core.rbac.ROLE_PERMISSIONS changes without the file
being exported again (python manage.py export_rbac_matrix).
"""

from __future__ import annotations

from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

from apps.core.management.commands.export_rbac_matrix import EXPORT_PATH, rendered


class RbacMatrixExportTest(SimpleTestCase):
    def test_the_gateways_copy_of_the_matrix_is_current(self):
        exported = (Path(settings.BASE_DIR) / EXPORT_PATH).read_text(encoding="utf-8")

        self.assertEqual(
            exported,
            rendered(),
            "The role → permission matrix changed; run "
            "`python manage.py export_rbac_matrix` so the Go gateway checks the same one.",
        )
