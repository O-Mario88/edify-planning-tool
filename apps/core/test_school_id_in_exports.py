"""Every export that lists schools carries the School ID (owner, 2026-10-19).

"Every export that contains a school list must include the authoritative
Edify School ID ... Create a repeatable export inventory or automated
coverage test so that future school-list exports cannot silently omit the
School ID." Earlier, 2026-09-27: "All exported plan should have school ID."

An export's header row is written in the source as a list or tuple of labels
(a CSV ``writerow``, a workbook's ``headers``, a table spec of ``(key,
label)`` pairs or ``C(key, label)`` columns). This reads every such literal in
the apps and refuses one that names a school ("School", "School Name") with
no "School ID" beside it.

The files allowed below hold lists that name a school and are not export
header rows: on-screen tables drawn cell by cell, permission and messaging
vocabularies, a "view by" choice, a module's ``__all__``. A new export is
not added here; it carries the School ID.
"""

from __future__ import annotations

import ast
from pathlib import Path

from django.test import SimpleTestCase

APPS = Path(__file__).resolve().parents[1]

SCHOOL_LABELS = frozenset({"School", "School Name", "School name"})
SCHOOL_ID = "School ID"

#: Lists that name a school and are not an export's header row.
NOT_EXPORTS = {
    "core/permissions.py": "object kinds a permission is checked on",
    "messaging/services.py": "the kinds of record a message may be about",
    "planning/country_execution/service.py": "the page's View by choices",
    "schools/models.py": "the module's __all__",
    "fund_requests/disbursement_dashboard_service.py": "an on-screen detail list",
    "frontend/views/ia_lending_views.py": "on-screen tables drawn cell by cell",
    "frontend/views/ia_school_evidence_views.py": "on-screen tables drawn cell by cell",
    "frontend/views/ia_stories_views.py": "an on-screen table drawn cell by cell",
    "frontend/views/impact_report_views.py": "on-screen tables drawn cell by cell",
}


def _labels(node) -> list[str]:
    """The string labels of a header-shaped literal: plain strings, and the
    first two string arguments of each pair or column constructor."""
    found = []
    for element in node.elts:
        if isinstance(element, ast.Constant) and isinstance(element.value, str):
            found.append(element.value)
            continue
        if isinstance(element, (ast.Tuple, ast.List)):
            parts = element.elts[:2]
        elif isinstance(element, ast.Call):
            parts = element.args[:2]
        else:
            continue
        found.extend(
            part.value
            for part in parts
            if isinstance(part, ast.Constant) and isinstance(part.value, str)
        )
    return found


def _sources():
    for path in sorted(APPS.rglob("*.py")):
        relative = path.relative_to(APPS).as_posix()
        name = path.name
        if "/migrations/" in f"/{relative}" or name.startswith("test"):
            continue
        if name == "tests.py":
            continue
        yield relative, path


def school_lists_without_id() -> list[str]:
    missing = []
    for relative, path in _sources():
        if relative in NOT_EXPORTS:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, (ast.List, ast.Tuple)) or len(node.elts) < 3:
                continue
            labels = _labels(node)
            if SCHOOL_LABELS.intersection(labels) and SCHOOL_ID not in labels:
                missing.append(f"apps/{relative}:{node.lineno} {labels[:6]}")
    return missing


class EveryExportListingSchoolsCarriesTheSchoolId(SimpleTestCase):
    def test_no_header_row_names_a_school_without_its_id(self):
        missing = school_lists_without_id()
        self.assertEqual(
            missing,
            [],
            "These header rows name a school with no 'School ID' beside it. "
            "Add the School ID (the school's business code, School.school_id), "
            "or, if the list is not an export, add its file to NOT_EXPORTS with "
            "the reason.",
        )

    def test_the_allowed_files_still_exist(self):
        for relative in NOT_EXPORTS:
            with self.subTest(file=relative):
                self.assertTrue((APPS / relative).exists())
