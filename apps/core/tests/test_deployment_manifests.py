from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase


class DeploymentManifestTests(SimpleTestCase):
    def test_compose_uses_one_healthy_shared_redis(self):
        compose = (Path(settings.BASE_DIR) / "docker-compose.yml").read_text()
        self.assertEqual(compose.count("redis://redis:6379/0"), 2)
        self.assertIn('test: ["CMD", "redis-cli", "ping"]', compose)
        self.assertEqual(compose.count("redis:\n        condition: service_healthy"), 2)

    def test_web_and_worker_receive_the_field_encryption_key(self):
        compose = (Path(settings.BASE_DIR) / "docker-compose.yml").read_text()
        web, worker = compose.split("\n  worker:", maxsplit=1)
        self.assertIn("FIELD_ENCRYPTION_KEY:", web)
        self.assertIn("FIELD_ENCRYPTION_KEY:", worker)

    def test_scheduler_is_dedicated_and_enabled_only_on_worker(self):
        compose = (Path(settings.BASE_DIR) / "docker-compose.yml").read_text()
        web, worker = compose.split("\n  worker:", maxsplit=1)
        self.assertIn("ENABLE_BACKGROUND_JOBS: ${ENABLE_BACKGROUND_JOBS:-false}", web)
        self.assertIn("command: python manage.py runscheduler", worker)
        self.assertIn('ENABLE_BACKGROUND_JOBS: "true"', worker)
        self.assertIn('RUN_MIGRATIONS: "false"', worker)
