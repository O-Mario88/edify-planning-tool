"""Every evidence path resolves inside the evidence store, or not at all.

Stored file names are generated — a uuid4 hex plus an extension taken from an
allowlist — so nothing in the application produces a name that escapes. But the
name is read back out of a database column each time a file is served,
converted or counted, and a path assembled by joining a column onto a directory
is only as safe as every row that column will ever hold. These pin the guard,
not the current contents of the table.
"""

from __future__ import annotations

import os

from django.test import TestCase

from apps.core.exceptions import BadRequest
from apps.evidence.services import evidence_dir, evidence_path
from apps.professional_development.uploads import pd_storage_dir, pd_storage_path

ESCAPES = (
    "../../../../etc/passwd",
    "..",
    "../secrets.env",
    "subdir/file.pdf",
    "/etc/passwd",
    "",
)


class EvidencePathContainmentTest(TestCase):
    def test_a_generated_name_resolves_inside_the_store(self):
        resolved = evidence_path("0123456789abcdef0123456789abcdef.pdf")
        self.assertTrue(resolved.startswith(os.path.realpath(evidence_dir()) + os.sep))

    def test_every_escaping_name_is_refused(self):
        for name in ESCAPES:
            with self.subTest(name=name), self.assertRaises(BadRequest):
                evidence_path(name)

    def test_a_name_is_never_read_from_outside_the_store(self):
        """The check is on the resolved path, not on the spelling: a name that
        looks harmless but resolves elsewhere is still refused."""
        with self.assertRaises(BadRequest):
            evidence_path("./../evidence/../../manage.py")


class ProfessionalDevelopmentPathContainmentTest(TestCase):
    def test_a_generated_name_resolves_inside_the_store(self):
        resolved = pd_storage_path("fedcba9876543210fedcba9876543210.pdf")
        self.assertTrue(
            resolved.startswith(os.path.realpath(pd_storage_dir()) + os.sep)
        )

    def test_every_escaping_name_is_refused(self):
        for name in ESCAPES:
            with self.subTest(name=name), self.assertRaises(BadRequest):
                pd_storage_path(name)
