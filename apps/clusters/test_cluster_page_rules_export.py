"""The Go gateway builds the Clusters page from the same rules as this
application.

Go owns District and Cluster management (owner brief, 2026-11-11); it embeds
platform/backend/internal/clusterpage/rules.json. This test fails the moment
one of the doors, statuses or labels it carries changes without the file
being exported again (python manage.py export_cluster_page_rules).
"""

from __future__ import annotations

from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

from apps.clusters.management.commands.export_cluster_page_rules import (
    EXPORT_PATH,
    rendered,
)


class ClusterPageRulesExportTest(SimpleTestCase):
    def test_the_gateways_copy_of_the_cluster_page_rules_is_current(self):
        exported = (Path(settings.BASE_DIR) / EXPORT_PATH).read_text(encoding="utf-8")

        self.assertEqual(
            exported,
            rendered(),
            "The Clusters page's rules changed; run "
            "`python manage.py export_cluster_page_rules` so the Go gateway "
            "builds the page the same way.",
        )
