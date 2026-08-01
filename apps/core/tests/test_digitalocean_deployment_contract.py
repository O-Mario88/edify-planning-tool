"""Deployment contract for DigitalOcean App Platform.

Most checks inspect manifests; isolated subprocesses also prove that production
settings fail closed and can construct the private Spaces backends.
"""

import os
import subprocess
import sys
from pathlib import Path

from django.test import SimpleTestCase


ROOT = Path(__file__).resolve().parents[3]


def _read(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def _safe_production_env() -> dict[str, str]:
    env = os.environ.copy()
    env.update(
        {
            "SECRET_KEY": "a" * 64,
            "JWT_SECRET": "",
            "FIELD_ENCRYPTION_KEY": "b" * 64,
            "SUPER_ADMIN_PASSWORD": "validation-only-password",
            "ALLOWED_HOSTS": "example.test",
            "AUTHZ_MODE": "enforce",
            "ENABLE_MOCK_DATA": "false",
            "ENABLE_DEV_ENDPOINTS": "false",
            "ENABLE_DEV_SEED": "false",
            "ENABLE_DEV_IMPORTS": "false",
            "PARTNER_ROLE_BRIDGE": "false",
            "SPACES_BUCKET_NAME": "edify-validation",
            "SPACES_REGION": "nyc3",
            "SPACES_ACCESS_KEY_ID": "validation-key",
            "SPACES_SECRET_ACCESS_KEY": "validation-secret",
            "SPACES_ENDPOINT_URL": "",
            "SPACES_PREFIX": "edify-production",
        }
    )
    return env


class DigitalOceanDeploymentContractTest(SimpleTestCase):
    def test_root_requirements_install_the_pinned_production_set(self):
        self.assertIn("-r requirements/prod.txt", _read("requirements.txt"))
        dependencies = _read("requirements/base.txt")
        for package in (
            "Django==",
            "gunicorn==",
            "psycopg[binary]==",
            "dj-database-url==",
            "whitenoise==",
            "django-storages[s3]==",
            "boto3==",
        ):
            self.assertIn(package, dependencies)

    def test_procfile_runs_asgi_gunicorn_on_the_platform_port(self):
        procfile = _read("Procfile")
        self.assertIn("web: gunicorn", procfile)
        self.assertIn("--worker-tmp-dir /dev/shm", procfile)
        self.assertIn("--bind 0.0.0.0:${PORT:-8080}", procfile)
        self.assertIn("uvicorn.workers.UvicornWorker", procfile)
        self.assertIn("config.asgi:application", procfile)

    def test_settings_support_platform_secrets_domain_database_and_static(self):
        base = _read("config/settings/base.py")
        prod = _read("config/settings/prod.py")

        self.assertIn('os.environ.get("SECRET_KEY")', base)
        self.assertIn('"DATABASE_URL",', base)
        self.assertIn("dj_database_url.parse(_db_url)", base)
        self.assertIn('"whitenoise.middleware.WhiteNoiseMiddleware"', base)
        self.assertLess(
            base.index('"django.middleware.security.SecurityMiddleware"'),
            base.index('"whitenoise.middleware.WhiteNoiseMiddleware"'),
        )
        self.assertIn('STATIC_URL = "/static/"', base)
        self.assertIn('STATIC_ROOT = BASE_DIR / "staticfiles"', base)
        self.assertIn('os.environ.get("DIGITALOCEAN_APP_DOMAIN")', prod)
        self.assertIn("CSRF_TRUSTED_ORIGINS", prod)
        self.assertIn('"BACKEND": "storages.backends.s3.S3Storage"', prod)
        self.assertIn('"private_uploads":', prod)
        self.assertIn('"default_acl": "private"', prod)
        self.assertIn('"querystring_auth": True', prod)
        self.assertIn("SPACES_BUCKET_NAME", prod)

    def test_python_runtime_is_pinned(self):
        self.assertEqual(_read("runtime.txt").strip(), "python-3.13.12")

    def test_production_refuses_to_boot_without_spaces_credentials(self):
        env = _safe_production_env()
        env["SPACES_BUCKET_NAME"] = ""
        result = subprocess.run(
            [sys.executable, "-c", "import config.settings.prod"],
            cwd=ROOT,
            env=env,
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("SPACES_BUCKET_NAME is required", result.stderr)

    def test_production_refuses_a_secret_below_the_documented_minimum(self):
        env = _safe_production_env()
        env["SECRET_KEY"] = "a" * 46  # over the old 16 bar, under the documented 50
        result = subprocess.run(
            [sys.executable, "-c", "import config.settings.prod"],
            cwd=ROOT,
            env=env,
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("must be at least 50 characters", result.stderr)

    def test_production_checks_secret_key_even_when_jwt_secret_is_strong(self):
        """A strong JWT_SECRET must not mask a weak Django signing key."""
        env = _safe_production_env()
        env["SECRET_KEY"] = "dev-only-insecure-secret-change-me"
        env["JWT_SECRET"] = "b" * 64
        result = subprocess.run(
            [sys.executable, "-c", "import config.settings.prod"],
            cwd=ROOT,
            env=env,
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("SECRET_KEY must not contain a development placeholder", result.stderr)

    def test_production_builds_private_spaces_backends(self):
        code = """
import config.settings.prod as settings
private = settings.STORAGES["private_uploads"]
media = settings.STORAGES["default"]
assert private["BACKEND"] == "storages.backends.s3.S3Storage"
assert private["OPTIONS"]["default_acl"] == "private"
assert private["OPTIONS"]["location"] == "edify-production/private"
assert media["OPTIONS"]["location"] == "edify-production/media"
assert private["OPTIONS"]["client_config"].connect_timeout == 5
"""
        result = subprocess.run(
            [sys.executable, "-c", code],
            cwd=ROOT,
            env=_safe_production_env(),
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)


class AppPlatformSpecTest(SimpleTestCase):
    """The committed App Platform spec must match how the image actually runs.

    The spec is the thing someone imports into DigitalOcean. If it drifts from
    the Dockerfile — wrong port, wrong health path, migrations configured in two
    places — the failure shows up as a broken production deploy rather than as a
    failing test.
    """

    @staticmethod
    def _spec() -> dict:
        import yaml

        return yaml.safe_load(_read(".do/app.yaml"))

    def test_spec_exists_and_builds_the_web_service_from_the_dockerfile(self):
        spec = self._spec()
        services = spec["services"]
        self.assertEqual(len(services), 1, "expected exactly one web service")
        web = services[0]
        self.assertEqual(web["dockerfile_path"], "Dockerfile")
        self.assertEqual(web["http_port"], 8080)

    def test_spec_probes_readiness_not_liveness(self):
        """A load balancer must not send traffic to an instance whose
        dependencies are down; /api/health/live answers before they are ready."""
        web = self._spec()["services"][0]
        self.assertEqual(web["health_check"]["http_path"], "/api/health/ready")

    def test_migrations_run_once_in_a_pre_deploy_job(self):
        spec = self._spec()
        jobs = {job["name"]: job for job in spec["jobs"]}
        migrate = jobs["migrate"]
        self.assertEqual(migrate["kind"], "PRE_DEPLOY")
        self.assertIn("migrate --noinput", migrate["run_command"])

    def test_web_service_does_not_also_migrate_on_boot(self):
        """Two web replicas booting together would otherwise each run migrate
        against the same database at the same time."""
        web = self._spec()["services"][0]
        envs = {env["key"]: env["value"] for env in web["envs"]}
        self.assertEqual(envs["RUN_MIGRATIONS"], "false")
        self.assertEqual(envs["DJANGO_SETTINGS_MODULE"], "config.settings.prod")

    def test_spec_keeps_every_production_gate_switched_off(self):
        web = self._spec()["services"][0]
        envs = {env["key"]: env["value"] for env in web["envs"]}
        self.assertEqual(envs["AUTHZ_MODE"], "enforce")
        for flag in (
            "ENABLE_MOCK_DATA",
            "ENABLE_DEV_ENDPOINTS",
            "ENABLE_DEV_SEED",
            "ENABLE_DEV_IMPORTS",
            "PARTNER_ROLE_BRIDGE",
        ):
            self.assertEqual(envs[flag], "false", flag)

    def test_spec_ships_no_real_secret_values(self):
        """The spec is committed. Every secret in it must be a placeholder."""
        spec = self._spec()
        components = spec["services"] + spec.get("jobs", [])
        for component in components:
            for env in component["envs"]:
                if env.get("type") == "SECRET":
                    self.assertTrue(
                        env["value"].startswith("REPLACE_ME"),
                        f"{component['name']}.{env['key']} looks like a real secret",
                    )


class BuildTimeStaticCollectionTest(SimpleTestCase):
    """collectstatic must not depend on the production boot gate.

    It did once. Each time prod.py gained a newly required setting, the
    placeholder environment baked into the Dockerfile fell behind it and the
    image stopped building — discovered by whoever next tried to deploy.
    """

    def test_dockerfile_collects_static_under_the_build_settings_module(self):
        dockerfile = _read("Dockerfile")
        self.assertIn(
            "DJANGO_SETTINGS_MODULE=config.settings.collectstatic", dockerfile
        )
        self.assertIn("collectstatic --noinput", dockerfile)

    def test_dockerfile_carries_no_placeholder_secrets(self):
        dockerfile = _read("Dockerfile")
        for leftover in ("JWT_SECRET=", "SUPER_ADMIN_PASSWORD=", "FIELD_ENCRYPTION_KEY="):
            self.assertNotIn(
                leftover,
                dockerfile,
                "build-time secret placeholders are what drifted before",
            )

    def test_build_settings_import_without_any_production_environment(self):
        """The whole point: no secrets, no Spaces credentials, still imports."""
        env = {
            key: value
            for key, value in os.environ.items()
            if not key.startswith(("SPACES_", "SECRET_", "JWT_", "FIELD_", "SUPER_ADMIN"))
        }
        env["DJANGO_SETTINGS_MODULE"] = "config.settings.collectstatic"
        result = subprocess.run(
            [sys.executable, "-c", "import config.settings.collectstatic"],
            cwd=ROOT,
            env=env,
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_build_and_runtime_agree_on_the_staticfiles_backend(self):
        """A manifest built by one backend and served by another 500s on every
        asset request, so these two must come from the same constant."""
        base = _read("config/settings/base.py")
        prod = _read("config/settings/prod.py")
        build = _read("config/settings/collectstatic.py")

        self.assertIn(
            'STATICFILES_STORAGE_BACKEND = "whitenoise.storage.'
            'CompressedManifestStaticFilesStorage"',
            base,
        )
        self.assertIn('"BACKEND": STATICFILES_STORAGE_BACKEND', prod)
        self.assertIn("STATICFILES_STORAGE_BACKEND", build)


class MigrationOwnershipTest(SimpleTestCase):
    def test_entrypoint_can_yield_migrations_to_the_platform(self):
        entrypoint = _read("docker-entrypoint.sh")
        self.assertIn('"${RUN_MIGRATIONS:-true}" = "true"', entrypoint)

    def test_entrypoint_still_migrates_by_default(self):
        """docker-compose and Railway have no pre-deploy hook; they rely on
        this default, so the flag must be opt-out rather than opt-in."""
        entrypoint = _read("docker-entrypoint.sh")
        self.assertIn("RUN_MIGRATIONS:-true", entrypoint)
