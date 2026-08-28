"""DEP-01: repository deployment records identify one production app."""

from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase


ROOT = Path(settings.BASE_DIR)
APP_ID = "8f8682cd-a00a-42d9-b9a6-4fa4b4140bde"
APP_NAME = "edify-planning-fra"


class DeploymentRecordsDescribeOneAppTest(SimpleTestCase):
    def test_the_operations_readme_names_the_verified_live_app(self):
        text = (ROOT / ".do" / "README.md").read_text(encoding="utf-8")
        self.assertIn(APP_ID, text)
        self.assertIn(APP_NAME, text)
        self.assertNotIn("dacdc3eb-0ebe-4b47-bea2-88fe1155347b", text)

    def test_the_live_audit_names_the_same_app(self):
        text = (ROOT / "docs" / "live-production-audit-2026-08-09.md").read_text(
            encoding="utf-8"
        )
        self.assertIn(APP_ID, text)
        self.assertIn(APP_NAME, text)

    def test_the_verified_topology_keeps_migrations_out_of_web_boot(self):
        text = (ROOT / ".do" / "README.md").read_text(encoding="utf-8")
        self.assertIn("2 × `apps-s-1vcpu-2gb`", text)
        self.assertIn("pre-deploy job `migrate`", text)
        self.assertIn("managed PostgreSQL 17", text)
