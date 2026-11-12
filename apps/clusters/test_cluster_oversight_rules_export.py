"""The Go gateway builds Cluster Oversight from the same rules as this
application.

Go owns District and Cluster management (owner brief, 2026-11-11); it embeds
platform/backend/internal/clusteroversight/rules.json. This test fails the
moment one of the doors, sections, columns, statuses or score parts it
carries changes without the file being exported again
(python manage.py export_cluster_oversight_rules).
"""

from __future__ import annotations

from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

from apps.clusters.management.commands.export_cluster_oversight_rules import (
    EXPORT_PATH,
    rendered,
)


class ClusterOversightRulesExportTest(SimpleTestCase):
    def test_the_gateways_copy_of_the_cluster_oversight_rules_is_current(self):
        exported = (Path(settings.BASE_DIR) / EXPORT_PATH).read_text(encoding="utf-8")

        self.assertEqual(
            exported,
            rendered(),
            "Cluster Oversight's rules changed; run "
            "`python manage.py export_cluster_oversight_rules` so the Go "
            "gateway builds the page the same way.",
        )
