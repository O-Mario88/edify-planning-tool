"""DEP-01: repository deployment records identify one production app."""

from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase


ROOT = Path(settings.BASE_DIR)
APP_ID = "fcd3a30a-9687-4c23-ad76-d54345d4bcfa"
APP_NAME = "edify-production"
RETIRED_APP_ID = "8f8682cd-a00a-42d9-b9a6-4fa4b4140bde"


class DeploymentRecordsDescribeOneAppTest(SimpleTestCase):
    def test_the_operations_readme_names_the_verified_live_app(self):
        text = (ROOT / ".do" / "README.md").read_text(encoding="utf-8")
        self.assertIn(APP_ID, text)
        self.assertIn(APP_NAME, text)
        self.assertNotIn(RETIRED_APP_ID, text)
        self.assertNotIn("dacdc3eb-0ebe-4b47-bea2-88fe1155347b", text)

    def test_the_dated_live_audit_remains_historical_evidence(self):
        text = (ROOT / "docs" / "live-production-audit-2026-08-09.md").read_text(
            encoding="utf-8"
        )
        self.assertIn(RETIRED_APP_ID, text)
        self.assertNotIn(APP_ID, text)

    def test_the_verified_topology_keeps_migrations_out_of_web_boot(self):
        text = (ROOT / ".do" / "README.md").read_text(encoding="utf-8")
        self.assertIn("1 × `apps-s-1vcpu-1gb-fixed`", text)
        self.assertIn("pre-deploy job `migrate`", text)
        self.assertIn("managed PostgreSQL 16", text)
        self.assertIn("RUN_MIGRATIONS=false", text)
