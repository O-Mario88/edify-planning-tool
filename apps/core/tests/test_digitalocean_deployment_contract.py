"""Deployment contract for DigitalOcean App Platform.

Most checks inspect manifests; isolated subprocesses also prove that production
settings fail closed and can construct the private Spaces backends.
"""

import os
import subprocess
import sys
from pathlib import Path

from django.test import SimpleTestCase, TestCase, override_settings


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
        self.assertIn(
            "web: python manage.py production_preflight && exec gunicorn", procfile
        )
        self.assertIn("--worker-tmp-dir /dev/shm", procfile)
        self.assertIn("--bind 0.0.0.0:${PORT:-8080}", procfile)
        self.assertIn("uvicorn.workers.UvicornWorker", procfile)
        self.assertIn("config.asgi:application", procfile)

    def test_container_runs_two_supervised_asgi_workers_by_default(self):
        dockerfile = _read("Dockerfile")
        self.assertIn("exec gunicorn", dockerfile)
        self.assertIn("--worker-class uvicorn.workers.UvicornWorker", dockerfile)
        self.assertIn('--workers \\"${WEB_CONCURRENCY:-2}\\"', dockerfile)
        self.assertIn("--worker-tmp-dir /dev/shm", dockerfile)
        self.assertIn("config.asgi:application", dockerfile)

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
        self.assertIn(
            "SECRET_KEY must not contain a deployment placeholder", result.stderr
        )

    def test_production_refuses_the_placeholder_this_repo_actually_ships(self):
        """The marker in .do/app.yaml is REPLACE_ME, and the gate did not look
        for it — it only knew the .env.example markers. The template string is
        30 characters so the length rule happens to stop it today; padded to 50
        it would have booted production on a public signing key.
        """
        env = _safe_production_env()
        env["SECRET_KEY"] = "REPLACE_ME_openssl_rand_hex_32_REPLACE_ME_openssl_rand"
        env["JWT_SECRET"] = env["SECRET_KEY"]
        self.assertGreaterEqual(
            len(env["SECRET_KEY"]),
            50,
            "the point of this test is a placeholder that clears the length rule",
        )
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
        self.assertIn("must not contain a deployment placeholder", result.stderr)

    def test_the_placeholder_check_is_case_insensitive(self):
        """Markers were compared against the raw value, so REPLACE_ME in caps
        missed a lower-cased marker list."""
        env = _safe_production_env()
        env["SECRET_KEY"] = "CHANGE-ME" + "x" * 60
        env["JWT_SECRET"] = env["SECRET_KEY"]
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
        self.assertIn("must not contain a deployment placeholder", result.stderr)

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

    def test_production_app_initialization_never_queries_the_database(self):
        """Django turns AppConfig database access into a RuntimeWarning.

        Promoting that warning to an error makes the startup invariant
        executable without requiring an unavailable database to hang or fail.
        """
        code = """
import warnings
warnings.filterwarnings("error", category=RuntimeWarning)
import django
django.setup()
"""
        env = _safe_production_env()
        env["DJANGO_SETTINGS_MODULE"] = "config.settings.prod"
        result = subprocess.run(
            [sys.executable, "-c", code],
            cwd=ROOT,
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
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
        """Pinned to intent, not to a command string.

        This asserted `migrate --noinput` literally, which failed the moment the
        command became `migrate_locked` — a change that makes the guarantee
        stronger, not weaker. What the contract is actually about is that a
        PRE_DEPLOY job applies migrations without prompting.
        """
        spec = self._spec()
        jobs = {job["name"]: job for job in spec["jobs"]}
        migrate = jobs["migrate"]
        self.assertEqual(migrate["kind"], "PRE_DEPLOY")
        command = migrate["run_command"]
        self.assertRegex(command, r"\bmanage\.py migrate(_locked)?\b")
        self.assertIn("--noinput", command)

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


@override_settings(
    # Exactly the production transport posture, plus the ALLOWED_HOSTS list
    # prod.py builds: custom domains, the platform domain, and loopback.
    SECURE_SSL_REDIRECT=True,
    SECURE_PROXY_SSL_HEADER=("HTTP_X_FORWARDED_PROTO", "https"),
    SECURE_REDIRECT_EXEMPT=[r"^api/health(/|$)"],
    ALLOWED_HOSTS=[
        "www.edifyplanning.app",
        "edifyplanning.app",
        "edify-planning-tool-abc12.ondigitalocean.app",
        "localhost",
        "127.0.0.1",
        # nosec B104 - the ALLOWED_HOSTS Host-header allowlist, not a socket
        # bind address; mirrors the same list (and the same annotation) in
        # config/settings/prod.py, which is what this test exists to reproduce.
        "0.0.0.0",  # nosec B104
    ],
    DEBUG=False,
)
class HealthProbeReachabilityTest(TestCase):
    """The configured health check must actually be able to answer 2xx.

    App Platform probes the container the way kubelet does — an HTTP GET at the
    pod's own address, so ``Host`` is an IP no ALLOWED_HOSTS entry can name in
    advance and there is no X-Forwarded-Proto for SECURE_PROXY_SSL_HEADER to
    read. Both of those turn the probe into a non-2xx under production settings
    (400 DisallowedHost, and a 301 to https), and the deploy then fails with
    nothing in the log but "readiness probe failed".

    Setting ``health_check.http_path`` in the spec is what exposed this: the
    platform default is a TCP connect, which never parses a Host header.
    """

    POD_PROBE = {"HTTP_HOST": "10.244.43.134:8080"}

    def test_readiness_probe_from_the_pod_address_answers_200(self):
        response = self.client.get("/api/health/ready", **self.POD_PROBE)
        self.assertEqual(response.status_code, 200, response.get("Location", ""))
        self.assertEqual(response.json()["db"], "up")

    def test_liveness_probe_from_the_pod_address_answers_200(self):
        response = self.client.get("/api/health/live", **self.POD_PROBE)
        self.assertEqual(response.status_code, 200, response.get("Location", ""))

    def test_probe_response_still_carries_the_standard_headers(self):
        """The probe is re-hosted, not short-circuited — it runs the whole
        middleware stack, so nothing downstream silently stops applying."""
        response = self.client.get("/api/health/ready", **self.POD_PROBE)
        self.assertIn("Content-Security-Policy", response)
        self.assertIn("x-correlation-id", response)

    def test_an_unknown_host_is_still_rejected_everywhere_else(self):
        """The rescue is scoped to the probe URLs. Any other path on a host
        Django does not recognise must still be a 400."""
        response = self.client.get("/login", **self.POD_PROBE)
        self.assertEqual(response.status_code, 400)

    def test_real_traffic_on_a_known_host_is_untouched(self):
        response = self.client.get(
            "/api/health/ready",
            HTTP_HOST="www.edifyplanning.app",
            HTTP_X_FORWARDED_PROTO="https",
        )
        self.assertEqual(response.status_code, 200)

    def test_spec_health_path_is_one_the_probe_can_actually_reach(self):
        """Ties the two halves together: if someone repoints the spec's health
        check at a URL outside the exempt/re-hosted set, this fails here rather
        than in a rolled-back deploy."""
        import yaml

        spec = yaml.safe_load(_read(".do/app.yaml"))
        path = spec["services"][0]["health_check"]["http_path"]
        from apps.core.middleware import HealthProbeHostMiddleware

        self.assertIn(path, HealthProbeHostMiddleware.PROBE_PATHS)
        response = self.client.get(path, **self.POD_PROBE)
        self.assertEqual(response.status_code, 200)


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

    def test_runtime_source_is_readable_independent_of_build_context_modes(self):
        dockerfile = _read("Dockerfile")
        self.assertIn("RUN chmod -R a+rX /app", dockerfile)
        self.assertLess(
            dockerfile.index("RUN chmod -R a+rX /app"),
            dockerfile.index("USER edify"),
        )

    def test_dockerfile_carries_no_placeholder_secrets(self):
        dockerfile = _read("Dockerfile")
        for leftover in (
            "JWT_SECRET=",
            "SUPER_ADMIN_PASSWORD=",
            "FIELD_ENCRYPTION_KEY=",
        ):
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
            if not key.startswith(
                ("SPACES_", "SECRET_", "JWT_", "FIELD_", "SUPER_ADMIN")
            )
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
        """docker-compose has no pre-deploy hook and relies on this default,
        so the flag must be opt-out rather than opt-in. App Platform runs
        migrations as a PRE_DEPLOY job and sets RUN_MIGRATIONS=false."""
        entrypoint = _read("docker-entrypoint.sh")
        self.assertIn("RUN_MIGRATIONS:-true", entrypoint)

    def test_every_production_process_route_runs_preflight(self):
        """Docker and Procfile deployments are both supported runtime routes."""
        entrypoint = _read("docker-entrypoint.sh")
        self.assertIn("python manage.py production_preflight", entrypoint)
        for process in ("daphne", "gunicorn", "runscheduler"):
            self.assertIn(f"config.settings.prod:*{process}*", entrypoint)
        self.assertLess(
            entrypoint.index("python manage.py production_preflight"),
            entrypoint.index('exec "$@"'),
        )

        procfile = _read("Procfile")
        for route in ("web:", "worker:"):
            line = next(
                line for line in procfile.splitlines() if line.startswith(route)
            )
            self.assertIn("python manage.py production_preflight && exec", line)

    def test_supported_deployment_manifests_all_route_through_docker_or_procfile(self):
        """A new deployment manifest cannot silently bypass startup gates."""
        dockerfile = _read("Dockerfile")
        self.assertIn('ENTRYPOINT ["./docker-entrypoint.sh"]', dockerfile)

        compose = _read("docker-compose.yml")
        self.assertEqual(compose.count("build: ."), 2)
        self.assertNotIn("entrypoint:", compose)

        import yaml

        app_spec = yaml.safe_load(_read(".do/app.yaml"))
        docker_components = app_spec["services"] + app_spec.get("jobs", [])
        self.assertTrue(docker_components)
        for component in docker_components:
            self.assertEqual(component["dockerfile_path"], "Dockerfile")
