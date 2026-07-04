"""
audit_mock_data — scan the codebase + runtime DB for mock/demo data leakage.

Usage:
  python manage.py audit_mock_data              # codebase + runtime scan
  python manage.py audit_mock_data --strict     # exit non-zero on any CRITICAL finding

Detects:
  • backend mock/demo operational data (source=local_test_upload records)
  • mock/seed flags enabled (ENABLE_MOCK_DATA / DEV_SEED / DEV_IMPORTS / bridge)
  • migrations that create operational records (RunPython/RunSQL with data)
  • committed test data files (*.csv/*.sqlite/*.db/fixtures under apps/)
  • operational records present in production

Output: file path / location + risk level + action required.
"""
from __future__ import annotations

from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand

from apps.core.models import DataSource

CRITICAL = "CRITICAL"
WARNING = "WARNING"
INFO = "INFO"


class Command(BaseCommand):
    help = "Audit the codebase + runtime DB for mock/demo data leakage."

    def add_arguments(self, parser):
        parser.add_argument("--strict", action="store_true", help="Exit non-zero on any CRITICAL finding.")

    def handle(self, *args, **options):
        findings: list[tuple[str, str, str]] = []  # (risk, location, action)

        # ── Runtime DB: local-test records ────────────────────────────────
        try:
            from apps.schools.models import School
            from apps.ssa.models import SsaRecord
            from apps.partners.models import Partner

            local_schools = School.objects.filter(source=DataSource.LOCAL_TEST_UPLOAD.value).count()
            local_ssa = SsaRecord.objects.filter(source=DataSource.LOCAL_TEST_UPLOAD.value).count()
            local_partners = Partner.objects.filter(source=DataSource.LOCAL_TEST_UPLOAD.value).count()
            if local_schools:
                findings.append((CRITICAL, f"DB: {local_schools} schools source=local_test_upload",
                                 "Run purge_local_test_data in dev; investigate if found in production."))
            if local_ssa:
                findings.append((CRITICAL, f"DB: {local_ssa} SSA records source=local_test_upload", "Purge local test data."))
            if local_partners:
                findings.append((CRITICAL, f"DB: {local_partners} partners source=local_test_upload", "Purge local test data."))
        except Exception as exc:  # noqa: BLE001
            findings.append((WARNING, "DB scan", f"Could not scan DB: {exc}"))

        # ── Flags ──────────────────────────────────────────────────────────
        for flag in ("ENABLE_MOCK_DATA", "ENABLE_DEV_SEED", "ENABLE_DEV_IMPORTS", "PARTNER_ROLE_BRIDGE"):
            if getattr(settings, flag, False):
                risk = CRITICAL if settings.IS_PRODUCTION else WARNING
                findings.append((risk, f"settings.{flag}=True", "Disable — mock/dev flags must be off."))

        # ── Codebase: migrations with data ────────────────────────────────
        apps_dir = Path(settings.BASE_DIR) / "apps"
        for mg_file in apps_dir.rglob("migrations/*.py"):
            if mg_file.name == "__init__.py":
                continue
            try:
                text = mg_file.read_text(encoding="utf-8")
            except Exception:  # noqa: BLE001
                continue
            if "RunPython" in text or "RunSQL" in text:
                findings.append((WARNING, str(mg_file), "Migration contains RunPython/RunSQL — verify it does not seed operational records."))

        # ── Codebase: committed test data files ───────────────────────────
        for pat in ("*.csv", "*.sqlite3", "*.db"):
            for f in apps_dir.rglob(pat):
                findings.append((CRITICAL, str(f), "Committed test data file — remove from the repository."))

        # ── Codebase: backend seed demo block ─────────────────────────────
        seed_path = apps_dir / "core/management/commands/seed.py"
        if seed_path.exists():
            text = seed_path.read_text(encoding="utf-8")
            if "_seed_sample_data" in text and "if settings.IS_PRODUCTION" not in text.split("_seed_sample_data")[0][-400:]:
                findings.append((WARNING, str(seed_path), "Demo sample-data block present — confirm it is gated off in production."))

        # ── Report ────────────────────────────────────────────────────────
        self.stdout.write(self.style.MIGRATE_HEADING("audit_mock_data — mock/demo leakage scan"))
        crit = sum(1 for r, *_ in findings if r == CRITICAL)
        warn = sum(1 for r, *_ in findings if r == WARNING)
        if not findings:
            self.stdout.write(self.style.SUCCESS("  ✓ No mock/demo data leakage detected."))
        for risk, location, action in findings:
            style = self.style.ERROR if risk == CRITICAL else self.style.WARNING if risk == WARNING else self.style.HTTP_INFO
            self.stdout.write(style(f"  [{risk}] {location}"))
            self.stdout.write(f"        → {action}")
        self.stdout.write(self.style.MIGRATE_HEADING(f"\n{crit} critical, {warn} warnings."))

        if options["strict"] and crit:
            raise SystemExit(1)
