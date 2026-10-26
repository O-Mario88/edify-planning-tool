"""Planning Oversight exports My Plan's tables (owner, 2026-10-26).

It exported one table of the owner's 29 columns from 2026-10-20; the owner
then asked: "If the IA select all then it should group those activities in
different sheets in the excel exported sheet not everything in one table ...
tables are exported exactly the way they are in My Plan tables". What the one
table proved still holds of the sheets: the Salesforce ID is written, the
page's filters narrow the file, a group training reads its own people, and
the country export is the same file.
"""

from __future__ import annotations

import csv
import io

from django.test import Client

from apps.core.rbac import EdifyRole
from apps.frontend.test_export_period_and_sessions import SessionFixture
from apps.frontend.test_oversight_filters_export import PL_EXPORT
from apps.my_plan import table_export

COUNTRY_EXPORT = "/country-planning-oversight/export"


class PlanningOversightExportsMyPlansTables(SessionFixture):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.cd_user, _ = cls._staff("cd@f.test", "Director", EdifyRole.COUNTRY_DIRECTOR)
        cls.visit.salesforce_activity_id = "SVE-0000001"
        cls.visit.save(update_fields=["salesforce_activity_id"])

    def tables(self, client=None, path=PL_EXPORT, **params):
        client = client or self.as_pl()
        response = client.get(
            path, {"fy": self.fy, "owner": self.james.id, "format": "csv", **params}
        )
        self.assertEqual(response.status_code, 200)
        body = b"".join(response.streaming_content).decode()
        return table_export.tables_from_csv(csv.reader(io.StringIO(body)))

    def test_the_sheets_are_my_plans_tables(self):
        self.assertEqual(
            [title for title in self.tables() if title in table_export.FIXED_TITLES],
            list(table_export.FIXED_TITLES),
        )

    def test_the_salesforce_id_is_written(self):
        ids = {row["Salesforce ID"] for row in self.tables()["School Visits"]}
        self.assertIn("SVE-0000001", ids)

    def test_the_pages_filters_still_narrow_it(self):
        tables = self.tables(activity_type="training")
        self.assertEqual(
            {title for title, rows in tables.items() if rows}, {"Trainings"}
        )
        self.assertEqual([r["School ID"] for r in tables["Trainings"]], ["s1"])

    def test_a_group_training_is_a_row_a_school_and_once_as_a_session(self):
        tables = self.tables()
        members = [r for r in tables["Trainings"] if r["School ID"].startswith("gt")]
        self.assertEqual(len(members), 4)
        self.assertEqual({r["Participants"] for r in members}, {"3"})
        (session,) = tables["Group Trainings"]
        self.assertEqual(session["Cluster Name"], "Kasangati Cluster")
        self.assertEqual(session["Participants"], "12")

    def test_the_country_export_is_the_same_sheets(self):
        client = Client()
        client.force_login(self.cd_user)
        self.assertEqual(
            list(self.tables(client, COUNTRY_EXPORT)),
            list(self.tables()),
        )


class MyPlanKeepsItsSheets(SessionFixture):
    def test_my_plan_still_exports_its_sheets(self):
        tables = self.my_plan_tables(fy=self.fy)
        self.assertIn("School Visits", tables)
        self.assertIn("Group Trainings", tables)
