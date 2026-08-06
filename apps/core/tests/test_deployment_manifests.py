from pathlib import Path

import yaml
from django.conf import settings
from django.test import SimpleTestCase

# Every variable config/settings/prod.py checks in its fail-closed boot gate.
# The gate runs on import, in every process, so a process type missing any of
# these exits 1 and crash-loops rather than starting degraded.
PROD_BOOT_REQUIRED_ENV = frozenset(
    {
        "DJANGO_SETTINGS_MODULE",
        "DATABASE_URL",
        "SECRET_KEY",
        "FIELD_ENCRYPTION_KEY",
        "SUPER_ADMIN_PASSWORD",
        "AUTHZ_MODE",
        "ENABLE_MOCK_DATA",
        "ENABLE_DEV_ENDPOINTS",
        "ENABLE_DEV_SEED",
        "ENABLE_DEV_IMPORTS",
        "PARTNER_ROLE_BRIDGE",
        "SPACES_BUCKET_NAME",
        "SPACES_REGION",
        "SPACES_ACCESS_KEY_ID",
        "SPACES_SECRET_ACCESS_KEY",
        "SPACES_PREFIX",
        "ALLOWED_HOSTS",
    }
)


def _app_platform_spec():
    return yaml.safe_load((Path(settings.BASE_DIR) / ".do" / "app.yaml").read_text())


def _envs(component):
    return {entry["key"]: entry.get("value") for entry in component.get("envs", [])}


class AppPlatformSpecTests(SimpleTestCase):
    """The App Platform spec is the deployment that serves real users.

    docker-compose.yml is covered below, but it describes the self-hosted path.
    For a long time these two disagreed about the scheduler and only the
    compose side was asserted, so the suite stayed green while the deployment
    people actually use ran none of the 17 registered jobs.
    """

    def test_spec_defines_exactly_one_scheduler_worker(self):
        workers = _app_platform_spec().get("workers") or []
        self.assertEqual(
            [w["name"] for w in workers],
            ["scheduler"],
            "App Platform must define the scheduler worker — without it "
            "ENABLE_BACKGROUND_JOBS is false in every process and no "
            "scheduled job runs in production.",
        )

    def test_scheduler_runs_the_scheduler_command_with_jobs_enabled(self):
        worker = (_app_platform_spec()["workers"])[0]
        self.assertEqual(worker["run_command"], "python manage.py runscheduler")
        self.assertEqual(_envs(worker).get("ENABLE_BACKGROUND_JOBS"), "true")

    def test_scheduler_is_never_scaled_past_one_replica(self):
        # Jobs take a database lock, but a second replica still doubles every
        # fire attempt. The scheduler is not designed to run concurrently.
        self.assertEqual((_app_platform_spec()["workers"])[0]["instance_count"], 1)

    def test_scheduler_carries_every_variable_prod_settings_boots_on(self):
        missing = PROD_BOOT_REQUIRED_ENV - set(
            _envs((_app_platform_spec()["workers"])[0])
        )
        self.assertEqual(
            missing,
            set(),
            f"scheduler worker would crash-loop on import; missing: {sorted(missing)}",
        )

    def test_web_service_does_not_also_run_jobs(self):
        # One scheduler, not one per web replica.
        web = next(s for s in _app_platform_spec()["services"] if s["name"] == "web")
        self.assertEqual(_envs(web).get("ENABLE_BACKGROUND_JOBS"), "false")

    def test_only_the_pre_deploy_job_migrates(self):
        spec = _app_platform_spec()
        for component in (*spec["services"], *(spec.get("workers") or [])):
            with self.subTest(component=component["name"]):
                self.assertEqual(_envs(component).get("RUN_MIGRATIONS"), "false")


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
