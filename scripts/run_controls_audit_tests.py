"""Run platform tests in a named disposable DB with fast fixture passwords.

No deployed settings are modified. Retain configured hashers for verification of
existing hash formats; MD5 is only the preferred test-fixture creation hasher.
This run is a functional audit, not a production password-strength benchmark.
"""

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
if os.environ.get("TEST_DATABASE_NAME") != "edify_controls_audit_test":
    raise SystemExit("Set TEST_DATABASE_NAME=edify_controls_audit_test explicitly.")
os.environ["DJANGO_SETTINGS_MODULE"] = "scripts.controls_audit_settings"
import pytest  # noqa: E402

raise SystemExit(
    pytest.main(sys.argv[1:] or ["apps", "-q", "--reuse-db", "--tb=short"])
)
