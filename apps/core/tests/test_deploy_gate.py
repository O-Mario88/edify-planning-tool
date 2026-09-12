"""Production follows CI, and something outside the platform watches it
(AEGIS review, 2026-09-12)."""

from __future__ import annotations

from pathlib import Path

from django.test import SimpleTestCase

ROOT = Path(__file__).resolve().parents[3]


class DeployFollowsCiTest(SimpleTestCase):
    def setUp(self):
        self.deploy = (ROOT / ".github/workflows/deploy.yml").read_text()

    def test_the_deployment_is_created_only_after_a_green_ci_run_on_main(self):
        self.assertIn("workflow_run:", self.deploy)
        self.assertIn("workflows: [CI]", self.deploy)
        self.assertIn("branches: [main]", self.deploy)
        self.assertIn("github.event.workflow_run.conclusion == 'success'", self.deploy)
        self.assertIn("doctl apps create-deployment", self.deploy)

    def test_it_is_harmless_until_the_owner_adds_the_secrets(self):
        self.assertIn("DIGITALOCEAN_ACCESS_TOKEN", self.deploy)
        self.assertIn("DIGITALOCEAN_APP_ID", self.deploy)
        self.assertIn("are not both set", self.deploy)

    def test_the_run_reads_the_triggering_commit_through_env_not_expansion(self):
        # zizmor's template-injection audit: a run block must not expand
        # attacker-influenced event fields inline.
        run_blocks = self.deploy.split("run: |")[1:]
        for block in run_blocks:
            self.assertNotIn("${{ github.event", block.split("\n      - name")[0])
        self.assertIn(
            "HEAD_SHA: ${{ github.event.workflow_run.head_sha }}", self.deploy
        )

    def test_the_deploy_spec_records_the_intent_and_the_docs_say_how(self):
        for path in (".do/app.yaml", ".do/staging.yaml"):
            with self.subTest(path=path):
                spec = (ROOT / path).read_text()
                self.assertNotIn("deploy_on_push: true", spec)
                self.assertIn("deploy.yml", spec)
        self.assertIn(
            "## 3b. Deploys follow CI, not the push", (ROOT / "DEPLOY.md").read_text()
        )


class UptimeProbeTest(SimpleTestCase):
    def test_something_outside_the_platform_asks_every_ten_minutes(self):
        uptime = (ROOT / ".github/workflows/uptime.yml").read_text()
        self.assertIn('cron: "*/10 * * * *"', uptime)
        self.assertIn("https://edifyplanning.app/api/health/ready", uptime)
        self.assertIn("https://edifyplanning.app/login", uptime)
        self.assertIn('d.get("db") == "up"', uptime)
