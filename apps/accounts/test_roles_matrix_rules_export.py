"""The Go gateway builds the Roles & Permissions matrix from the same rules as this application.

Go embeds platform/backend/internal/rolesmatrix/rules.json. This test fails
the moment one of the doors, roles, labels or limits it carries changes
without the file being exported again (python manage.py
export_roles_matrix_rules).
"""

from __future__ import annotations

from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

from apps.accounts.management.commands.export_roles_matrix_rules import (
    EXPORT_PATH,
    rendered,
)


class RolesMatrixRulesExportTest(SimpleTestCase):
    def test_the_gateways_copy_of_the_roles_matrix_rules_is_current(self):
        exported = (Path(settings.BASE_DIR) / EXPORT_PATH).read_text(encoding="utf-8")

        self.assertEqual(
            exported,
            rendered(),
            "The Roles & Permissions matrix's rules changed; run "
            "`python manage.py export_roles_matrix_rules` so the Go gateway "
            "builds the page the same way.",
        )
