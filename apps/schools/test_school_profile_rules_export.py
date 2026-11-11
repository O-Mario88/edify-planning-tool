"""The Go gateway builds School Profiles from the same rules as this
application.

Go owns School Profiles (owner brief, 2026-11-11); it embeds
platform/backend/internal/schoolprofile/rules.json. This test fails the moment
one of the labels, visit-gate vocabularies or doors it carries changes without
the file being exported again (python manage.py export_school_profile_rules).
"""

from __future__ import annotations

from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

from apps.schools.management.commands.export_school_profile_rules import (
    EXPORT_PATH,
    rendered,
)


class SchoolProfileRulesExportTest(SimpleTestCase):
    def test_the_gateways_copy_of_the_profile_rules_is_current(self):
        exported = (Path(settings.BASE_DIR) / EXPORT_PATH).read_text(encoding="utf-8")

        self.assertEqual(
            exported,
            rendered(),
            "The School Profile's rules changed; run "
            "`python manage.py export_school_profile_rules` so the Go gateway "
            "builds the profile the same way.",
        )
