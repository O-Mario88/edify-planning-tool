"""Filters and exports.

An export is only trustworthy if it is the page: same scope, same filters, same
totals. The risk it guards against is a supervisor downloading a file that
contains rows the page would not have shown them.
"""

from __future__ import annotations

import csv
import io
from datetime import date, timedelta

from django.test import Client, TestCase

from apps.accounts.models import (
    StaffProfile,
    StaffSchoolAssignment,
    StaffSupervisorAssignment,
    User,
)
from apps.activities.models import Activity, ActivityScheduleCostLine
from apps.core.fy import get_operational_fy
from apps.core.rbac import EdifyRole
from apps.geography.models import District, Region
from apps.partners.models import Partner
from apps.schools.models import School

PL_EXPORT = "/team-planning-oversight/export"
PL_URL = "/team-planning-oversight/"


class FilterExportFixture(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.fy = get_operational_fy()
        cls.region = Region.objects.create(id="r1", name="Central")
        cls.district = District.objects.create(
            id="d1", name="Kampala", region=cls.region
        )
        cls.pl_user, cls.pl = cls._staff(
            "pl@f.test", "Team Lead", EdifyRole.COUNTRY_PROGRAM_LEAD
        )
        cls.james_user, cls.james = cls._staff("j@f.test", "James", EdifyRole.CCEO)
        cls.other_user, cls.other = cls._staff("o@f.test", "Outsider", EdifyRole.CCEO)
        StaffSupervisorAssignment.objects.create(
            supervisee=cls.james, supervisor=cls.pl
        )

        cls.school = School.objects.create(
            school_id="s1",
            name="Alpha Primary",
            district=cls.district,
            region=cls.region,
        )
        StaffSchoolAssignment.objects.create(staff=cls.james, school_id=cls.school.id)
        cls.partner = Partner.objects.create(name="Partner X", active_status=True)

        cls.visit = cls._activity("school_visit", cls.james, cost=40_000)
        cls.training = cls._activity("training", cls.james, cost=60_000)
        cls.partner_work = cls._activity(
            "school_visit", None, cost=25_000, partner=cls.partner, monitor=cls.james
        )
        # Another team's work, which must never reach this PL's export.
        cls.foreign = cls._activity("school_visit", cls.other, cost=99_000)

    @classmethod
    def _staff(cls, email, name, role):
        user = User.objects.create(
            email=email,
            name=name,
            roles=[role.value],
            active_role=role.value,
            is_active=True,
        )
        return user, StaffProfile.objects.create(user=user, title=name)

    @classmethod
    def _activity(cls, kind, owner, *, cost, partner=None, monitor=None):
        planned = date.today() + timedelta(days=6)
        activity = Activity.objects.create(
            activity_type=kind,
            school=cls.school,
            fy=cls.fy,
            quarter="Q1",
            planned_date=planned,
            planned_month=planned.month,
            status="partner_scheduled" if partner else "scheduled",
            responsible_staff_id=owner.id if owner else None,
            monitored_by_staff_id=monitor.id if monitor else None,
            assigned_partner_id=partner.id if partner else None,
        )
        ActivityScheduleCostLine.objects.create(
            activity=activity,
            cost_setting_key="k",
            label="Transport",
            unit_cost=cost,
            quantity=1,
            amount=cost,
        )
        return activity

    def as_pl(self):
        client = Client()
        client.force_login(self.pl_user)
        return client

    def export_rows(self, **params):
        params.setdefault("owner", self.james.id)
        response = self.as_pl().get(PL_EXPORT, params)
        self.assertEqual(response.status_code, 200)
        body = b"".join(response.streaming_content).decode()
        return list(csv.reader(io.StringIO(body)))

    def export_tables(self, **params) -> dict[str, list[dict]]:
        """The export's sheets (apps.core.plan_export), each a list of rows
        keyed by column heading."""
        from apps.core import plan_export

        return plan_export.tables_from_csv(self.export_rows(**params))

    def export_records(self, **params) -> list[dict]:
        return [row for rows in self.export_tables(**params).values() for row in rows]


class ExportScopeTest(FilterExportFixture):
    def test_the_export_never_contains_another_team(self):
        rows = self.export_rows(fy=self.fy)

        body = "\n".join(",".join(row) for row in rows)
        self.assertIn("Alpha Primary", body)
        self.assertNotIn("99000", body, "another team's cost must not be exported")

    def test_the_export_totals_match_the_page(self):
        exported_total = sum(
            int(row["Cost (UGX)"] or 0) for row in self.export_records(fy=self.fy)
        )

        from apps.planning import oversight_service as svc

        page_items = svc.build_items(self.pl_user, fy=self.fy)
        owner_ids = {self.james.id, self.james.user_id}
        page_total = svc.summarize(
            [
                item
                for item in page_items
                if item.operational_owner_id in owner_ids
                or item.managing_staff_id in owner_ids
            ]
        )["planned_budget"]
        self.assertEqual(exported_total, page_total)

    def test_the_export_is_the_owners_columns(self):
        """Owner, 2026-10-12: the columns of each sheet, named one by one;
        they replace the wide attribution table of 2026-09-22. Who does the
        work is the Executor."""
        from apps.core import plan_export

        lines = self.export_rows(fy=self.fy)
        self.assertIn(list(plan_export.VISIT_HEADERS), lines)
        self.assertIn(list(plan_export.TRAINING_HEADERS), lines)
        self.assertIn(list(plan_export.MEETING_HEADERS), lines)
        self.assertIn(list(plan_export.PARTNER_HEADERS), lines)
        self.assertIn(list(plan_export.OTHER_HEADERS), lines)
        # The sheets, in the owner's order, the Budget of those activities last.
        self.assertEqual(
            [
                line[0]
                for line in lines
                if len(line) == 1 and line[0] in plan_export.SHEET_ORDER
            ],
            list(plan_export.SHEET_ORDER),
        )
        self.assertEqual(
            plan_export.VISIT_HEADERS,
            (
                "School ID",
                "School Name",
                "District",
                "District Type",
                "Activity",
                "Planned Date",
                "Executor",
                "Purpose of Visit",
                "Focus Intervention",
                "Cost (UGX)",
                "Budget Status",
                "Verification",
                "Salesforce ID",
                # "Evidence" left with the upload (UPLOAD-OFF, 2026-10-13).
                "Status",
            ),
        )
        self.assertEqual(
            plan_export.TRAINING_HEADERS,
            (
                "Cluster Name",
                "District",
                "District Type",
                "Planned Date",
                "Executor",
                "Training",
                "SSA Intervention",
                "Participants",
                "Cost (UGX)",
                "Budget Status",
                "Verification",
                "Salesforce ID",
                # "Evidence" left with the upload (UPLOAD-OFF, 2026-10-13).
                "Status",
            ),
        )
        for row in self.export_records(fy=self.fy):
            self.assertIn(
                row["District Type"],
                ("Primary District", "Secondary District", "Mixed", ""),
            )
            # Who does the work: the Executor, or the Partner on its sheet.
            self.assertTrue(row.get("Executor") or row.get("Partner"))

    def test_the_export_carries_no_free_text_notes(self):
        """A plan, not a record store — evidence and notes stay behind."""
        from apps.core import plan_export

        for header in plan_export.ALL_HEADERS:
            for forbidden in ("Evidence file", "Note", "Message"):
                with self.subTest(column=forbidden):
                    self.assertNotIn(forbidden, header)


class FilterTest(FilterExportFixture):
    def test_filtering_by_activity_type_narrows_both_page_and_export(self):
        tables = self.export_tables(fy=self.fy, activity_type="training")

        self.assertEqual(len(tables["Group Trainings"]), 1)
        self.assertEqual(tables["Cluster Meetings"], [])
        self.assertEqual(tables["School Visits"], [])
        self.assertEqual(tables["Other Activities"], [])

    def test_filtering_by_executor_type_separates_partner_from_staff(self):
        partner_rows = self.export_records(fy=self.fy, executor_type="partner")
        staff_rows = self.export_records(fy=self.fy, executor_type="staff")

        self.assertEqual(len(partner_rows), 1)
        self.assertEqual(len(staff_rows), 2)

    def test_an_applied_filter_changes_the_pages_totals_too(self):
        body = (
            self.as_pl()
            .get(
                PL_URL,
                {
                    "fy": self.fy,
                    "owner": self.james.id,
                    "activity_type": "training",
                },
            )
            .content.decode()
        )

        # 60,000 is the training; 40,000 the visit that the filter excluded.
        self.assertIn("UGX 60,000", body)
        self.assertNotIn("UGX 100,000", body)

    def test_the_filter_options_only_offer_values_that_exist(self):
        """A filter that can only return nothing reads as a broken page."""
        from apps.frontend.views.oversight_views import _filter_options
        from apps.planning import oversight_service as svc

        options = _filter_options(svc.build_items(self.pl_user, fy=self.fy))

        self.assertEqual(
            sorted(options["activity_types"]), ["school_visit", "training"]
        )
        self.assertEqual([name for _, name in options["partners"]], ["Partner X"])


class CustomExportPeriodAndDrawerTest(FilterExportFixture):
    def test_month_to_month_export_defaults_to_excel(self):
        client = self.as_pl()
        resp = client.get(
            PL_EXPORT,
            {
                "fy": self.fy,
                "period_type": "month_range",
                "from_month": "10",
                "to_month": "12",
                "owner": self.james.id,
            },
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(
            resp["Content-Type"],
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        self.assertTrue(resp["Content-Disposition"].endswith('.xlsx"'))

    def test_completed_visits_and_trainings_filtering_in_custom_month_range(self):
        # Create a completed visit in November
        nov_date = date(int(self.fy) - 1, 11, 15)
        self._activity(
            "school_visit",
            self.james,
            cost=25_000,
        )
        completed_act = Activity.objects.create(
            activity_type="school_visit",
            school=self.school,
            fy=self.fy,
            quarter="Q1",
            planned_date=nov_date,
            planned_month=11,
            status="completed",
            responsible_staff_id=self.james.id,
        )
        ActivityScheduleCostLine.objects.create(
            activity=completed_act,
            cost_setting_key="k",
            label="Fuel",
            unit_cost=30_000,
            quantity=1,
            amount=30_000,
        )

        # Export as CSV with month range 10 to 12 and status completed
        rows = self.export_records(
            fy=self.fy,
            period_type="month_range",
            from_month="10",
            to_month="12",
            status="completed",
            activity_type="visits_trainings",
            format="csv",
        )
        # The one completed row.
        self.assertEqual(len(rows), 1)
        self.assertIn("omplete", rows[0]["Status"])

    def test_drawers_render_successfully(self):
        client = self.as_pl()
        drawers = [
            "/team-planning-oversight/export-drawer",
            "/country-planning-oversight/export-drawer",
            "/partner-oversight/export-drawer",
            "/team-planning-oversight/projects/export-drawer",
            "/cluster-oversight/export-drawer",
            "/my-plan/export-drawer",
        ]
        for url in drawers:
            with self.subTest(drawer=url):
                resp = client.get(url, {"fy": self.fy})
                self.assertEqual(resp.status_code, 200)
                body = resp.content.decode()
                self.assertIn("From (Month) to (Month)", body)
                self.assertIn("from_month", body)
                self.assertIn("to_month", body)
                self.assertIn("Download Excel", body)
                self.assertIn("format", body)
                self.assertIn("xlsx", body)

    def test_cluster_oversight_export_excel(self):
        client = self.as_pl()
        resp = client.get(
            "/cluster-oversight/export", {"fy": self.fy, "format": "xlsx"}
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(
            resp["Content-Type"],
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

    def test_my_plan_custom_month_export_excel(self):
        client = self.as_pl()
        resp = client.get(
            "/my-plan/",
            {
                "fy": self.fy,
                "period_type": "month_range",
                "from_month": "10",
                "to_month": "12",
                "export": "xlsx",
            },
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(
            resp["Content-Type"],
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )


class EveryoneAtOnceTest(FilterExportFixture):
    """Owner, 2026-10-12: "make sure the cd and ia can export for everyone at
    once not by program lead as currently it is"."""

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.cd_user, _ = cls._staff("cd@f.test", "Director", EdifyRole.COUNTRY_DIRECTOR)
        cls.ia_user, _ = cls._staff(
            "ia@f.test", "Assessor", EdifyRole.IMPACT_ASSESSMENT
        )
        # A second Lead, whose officer holds the "foreign" visit.
        cls.pl2_user, cls.pl2 = cls._staff(
            "pl2@f.test", "Second Lead", EdifyRole.COUNTRY_PROGRAM_LEAD
        )
        StaffSupervisorAssignment.objects.create(
            supervisee=cls.other, supervisor=cls.pl2
        )

    def _costs(self, user, path, **params) -> list[int]:
        from apps.core import plan_export

        client = Client()
        client.force_login(user)
        response = client.get(path, {"fy": self.fy, **params})
        self.assertEqual(response.status_code, 200)
        body = b"".join(response.streaming_content).decode()
        tables = plan_export.tables_from_csv(csv.reader(io.StringIO(body)))
        return sorted(
            int(row["Cost (UGX)"] or 0) for rows in tables.values() for row in rows
        )

    EVERYONE = [25_000, 40_000, 60_000, 99_000]

    def test_the_team_export_is_everyone_for_the_cd_and_ia(self):
        for user in (self.cd_user, self.ia_user):
            with self.subTest(role=user.active_role):
                self.assertEqual(self._costs(user, PL_EXPORT), self.EVERYONE)
                self.assertEqual(
                    self._costs(user, PL_EXPORT, program_lead="all"), self.EVERYONE
                )

    def test_one_leads_team_is_still_a_choice(self):
        self.assertEqual(
            self._costs(self.cd_user, PL_EXPORT, program_lead=self.pl2.id), [99_000]
        )

    def test_the_country_export_is_everyone_too(self):
        path = "/country-planning-oversight/export"
        self.assertEqual(self._costs(self.cd_user, path), self.EVERYONE)
        self.assertEqual(
            self._costs(self.cd_user, path, program_lead="all"), self.EVERYONE
        )

    def test_the_drawer_opens_on_everyone_whatever_tab_the_page_is_on(self):
        client = Client()
        client.force_login(self.cd_user)
        for path in (
            "/team-planning-oversight/export-drawer",
            "/country-planning-oversight/export-drawer",
        ):
            html = client.get(
                path, {"fy": self.fy, "program_lead": self.pl.id}
            ).content.decode()
            self.assertIn('<option value="all" selected>Everyone</option>', html)
            self.assertIn("Second Lead&#x27;s team", html)
            # The page's tab is not carried in as a hidden narrowing.
            self.assertNotIn('type="hidden" name="program_lead"', html)

    def test_a_program_lead_is_not_offered_other_teams(self):
        html = (
            self.as_pl()
            .get("/team-planning-oversight/export-drawer", {"fy": self.fy})
            .content.decode()
        )
        self.assertNotIn("Whose Plans", html)
