"""§41 — evidence storage runtime health (writable + free disk space),
distinct from apps.core.boot_gates' boot-time static-assets check."""

from __future__ import annotations

import shutil
import tempfile
from unittest.mock import patch

from django.test import SimpleTestCase

from apps.evidence.health import evidence_storage_health


class EvidenceStorageHealthTest(SimpleTestCase):
    # Every test here is filesystem-only except test_wired_into_system_health_
    # report, which calls the real apps.system_health.services.report()
    # (school aggregation queries) — SimpleTestCase blocks DB access by
    # default, so it must be explicitly allowed here rather than pulling in
    # TestCase's per-test transaction wrapping for tests that don't need it.
    databases = {"default"}

    def test_unconfigured_storage_dir_is_critical(self):
        with self.settings(EVIDENCE_STORAGE_DIR=None):
            result = evidence_storage_health()
        self.assertEqual(len(result["checks"]), 1)
        self.assertEqual(result["checks"][0]["severity"], "critical")
        self.assertEqual(result["checks"][0]["key"], "evidence_storage_configured")

    def test_writable_dir_reports_ok(self):
        tmp = tempfile.mkdtemp(prefix="edify-evidence-health-")
        try:
            with self.settings(EVIDENCE_STORAGE_DIR=tmp):
                result = evidence_storage_health()
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        by_key = {c["key"]: c for c in result["checks"]}
        self.assertEqual(by_key["evidence_storage_writable"]["severity"], "ok")
        self.assertEqual(by_key["evidence_storage_disk_space"]["severity"], "ok")

    def test_unwritable_dir_is_critical_and_skips_disk_space_check(self):
        with (
            self.settings(EVIDENCE_STORAGE_DIR="/nonexistent"),
            patch("os.makedirs", side_effect=OSError("Permission denied")),
        ):
            result = evidence_storage_health()
        by_key = {c["key"]: c for c in result["checks"]}
        self.assertEqual(by_key["evidence_storage_writable"]["severity"], "critical")
        # No disk-space probe on a directory that isn't even reachable.
        self.assertNotIn("evidence_storage_disk_space", by_key)

    def test_low_disk_space_is_critical(self):
        tmp = tempfile.mkdtemp(prefix="edify-evidence-health-lowdisk-")
        try:
            fake_usage = shutil._ntuple_diskusage(total=10**12, used=10**12, free=1024)
            with (
                self.settings(EVIDENCE_STORAGE_DIR=tmp),
                patch("shutil.disk_usage", return_value=fake_usage),
            ):
                result = evidence_storage_health()
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        by_key = {c["key"]: c for c in result["checks"]}
        self.assertEqual(by_key["evidence_storage_disk_space"]["severity"], "critical")

    def test_wired_into_system_health_report(self):
        from apps.system_health.services import report

        data = report()
        self.assertIn("evidenceStorage", data)
        self.assertIn("checks", data["evidenceStorage"])
