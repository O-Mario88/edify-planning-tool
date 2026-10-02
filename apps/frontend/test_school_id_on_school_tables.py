"""Every table that lists schools has a School ID column (owner, 2026-10-02).

"make sure every table with a school list has school ID (School ID rule
Should apply on every table in the platform)". A school's name is not unique
— two "St Mary's Primary" in one district is ordinary — so a list of schools
without the School ID cannot be acted on.

A table lists schools when its heading row has a School column, or a column
that is a school on some rows and a cluster on others ("School / Cluster").
The ID is a column of its own, headed School ID, beside the name: it used to
be accepted inside the name cell (``{% school_identity %}``), where it could
not be sorted, scanned down or copied (owner, same day: "fix those too").
This reads every template, so a new table of schools cannot ship without one.
"""

from __future__ import annotations

import re
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

#: Headings that say the rows are schools. "Schools" is a count of them.
SCHOOL_HEADINGS = frozenset({"School", "School Name", "School name"})

#: A table written by hand, or with the ``{% data_table %}`` component, whose
#: body holds the heading row the same way.
_TABLE = re.compile(
    r"<table\b.*?</table>|\{% data_table\b.*?\{% enddata_table %\}", flags=re.S
)

#: Tables whose rows are something else that carries its own identifier.
OWN_IDENTIFIER = ("Venue ID",)


def _labels(head: str) -> list[str]:
    cells = re.findall(r"<th\b[^>]*>(.*?)</th>", head, flags=re.S)
    plain = (re.sub(r"<[^>]+>|\{%.*?%\}|\{\{.*?\}\}", " ", cell) for cell in cells)
    return [re.sub(r"\s+", " ", label).strip() for label in plain]


def _names_schools(label: str) -> bool:
    """A School column, or one shared with clusters ("School / Cluster",
    "School or cluster")."""
    if label in SCHOOL_HEADINGS:
        return True
    low = label.lower()
    return low.startswith("school") and ("/" in low or " or " in low)


class SchoolTablesShowTheSchoolIdTest(SimpleTestCase):
    def _tables(self):
        root = Path(settings.BASE_DIR) / "templates"
        for path in sorted(root.rglob("*.html")):
            text = path.read_text()
            name = str(path.relative_to(root))
            for match in _TABLE.finditer(text):
                table = match.group(0)
                head = re.search(r"<thead.*?</thead>", table, flags=re.S)
                if head is None:
                    continue
                labels = _labels(head.group(0))
                if not any(_names_schools(label) for label in labels):
                    continue
                if any(own in labels for own in OWN_IDENTIFIER):
                    continue
                line = text[: match.start()].count("\n") + 1
                yield f"{name}:{line}", labels, table

    def test_every_table_of_schools_has_a_school_id_column(self):
        missing = []
        seen = 0
        for where, labels, _table in self._tables():
            seen += 1
            if "School ID" not in labels:
                missing.append(f"{where} {labels[:5]}")
        self.assertGreater(seen, 80, "the scan found too few tables to mean anything")
        self.assertEqual(missing, [], "tables of schools with no School ID column")

    def test_the_school_id_sits_beside_the_school(self):
        apart = []
        for where, labels, _table in self._tables():
            if "School ID" not in labels:
                continue
            at = labels.index("School ID")
            names = [i for i, label in enumerate(labels) if _names_schools(label)]
            if not any(abs(i - at) == 1 for i in names):
                apart.append(f"{where} {labels[:6]}")
        self.assertEqual(apart, [], "School ID is not next to the school it names")

    def test_the_id_is_not_also_drawn_inside_the_name_cell(self):
        doubled = [
            where
            for where, labels, table in self._tables()
            if "School ID" in labels and "{% school_identity" in table
        ]
        self.assertEqual(doubled, [], "the School ID is shown twice on a row")

    def test_the_project_tables_name_the_district(self):
        """Owner, 2026-10-02: "Add the district column on the project tables
        so that the users can know which district the schools assigned
        belongs"."""
        root = Path(settings.BASE_DIR) / "templates"
        for name in (
            "pages/projects/monitoring.html",
            "pages/projects/detail.html",
            "partials/projects/project_schools_table.html",
            "partials/projects/planning_workspace.html",
            "partials/projects/my_plan_activity_table.html",
        ):
            with self.subTest(template=name):
                text = (root / name).read_text()
                heads = " ".join(
                    " ".join(_labels(head))
                    for head in re.findall(r"<thead.*?</thead>", text, flags=re.S)
                )
                self.assertIn("School ID", heads)
                self.assertIn("District", heads)
