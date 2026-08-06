"""`.do/app.yaml` must keep warning people not to apply it to the running app.

The file describes a *new* app. The running one was created separately and has
never been configured from it, so the two disagree about the app name, the
service name, the database name, and all twenty secrets — which the file still
carries as REPLACE_ME placeholders.

`doctl apps update --spec` replaces the entire spec rather than merging, so
applying this file to production would delete every app-level env (all
secrets), rename the database out from under `${db.DATABASE_URL}`, and recreate
the service under a different name. Its header used to recommend exactly that
command.

The placeholders are not the bug and are not removed here — they are correct
for `doctl apps create`, which is what the file is for. What has to hold is
that nobody reads the header and points it at production. That is a comment,
and comments rot, so it is asserted.
"""

from __future__ import annotations

from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase


def _spec_text() -> str:
    return (Path(settings.BASE_DIR) / ".do" / "app.yaml").read_text(encoding="utf-8")


class DoSpecCarriesItsWarningTest(SimpleTestCase):
    def test_the_header_warns_against_applying_it_to_the_running_app(self):
        self.assertIn("DO NOT APPLY THIS FILE TO THE RUNNING APP", _spec_text())

    def test_the_header_does_not_recommend_apps_update(self):
        """`create` is fine — it is what this file is for. `update` is the one
        that replaces a live spec, and it must not appear as a suggestion."""
        header = _spec_text().split("name: edify-planning-tool", 1)[0]
        recommending = [
            line
            for line in header.splitlines()
            if "apps update" in line and "would break prod" not in line
        ]
        self.assertEqual(
            recommending,
            [],
            "the header must not present `doctl apps update --spec` as a "
            f"thing to run: {recommending}",
        )

    def test_it_points_at_the_safe_procedure(self):
        text = _spec_text()
        self.assertIn(".do/README.md", text)
        self.assertIn("do_spec_diff.py", text)

    def test_the_safe_procedure_actually_exists(self):
        # A pointer to a missing file is worse than no pointer.
        base = Path(settings.BASE_DIR)
        self.assertTrue((base / ".do" / "README.md").exists())
        self.assertTrue((base / "scripts" / "do_spec_diff.py").exists())
