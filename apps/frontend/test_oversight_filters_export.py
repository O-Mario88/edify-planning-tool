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
        response = self.as_pl().get(PL_EXPORT, params)
        self.assertEqual(response.status_code, 200)
        body = b"".join(response.streaming_content).decode()
        return list(csv.reader(io.StringIO(body)))


class ExportScopeTest(FilterExportFixture):
    def test_the_export_never_contains_another_team(self):
        rows = self.export_rows(fy=self.fy)

        body = "\n".join(",".join(row) for row in rows)
        self.assertIn("Alpha Primary", body)
        self.assertNotIn("99000", body, "another team's cost must not be exported")

    def test_the_export_totals_match_the_page(self):
        rows = self.export_rows(fy=self.fy)

        header, *data = rows
        cost_column = header.index("Planned cost (UGX)")
        exported_total = sum(int(row[cost_column] or 0) for row in data)

        from apps.planning import oversight_service as svc

        page_total = svc.summarize(svc.build_items(self.pl_user, fy=self.fy))[
            "planned_budget"
        ]
        self.assertEqual(exported_total, page_total)

    def test_the_export_names_every_attribution_column(self):
        header = self.export_rows(fy=self.fy)[0]

        for column in (
            "Planned by",
            "Operational owner",
            "Executor type",
            "Managing staff",
            "Supervising PL",
            "Partner",
        ):
            with self.subTest(column=column):
                self.assertIn(column, header)

    def test_the_export_carries_no_free_text_notes(self):
        """A plan, not a record store — evidence and notes stay behind."""
        header = self.export_rows(fy=self.fy)[0]

        for forbidden in ("Evidence file", "Note", "Message"):
            with self.subTest(column=forbidden):
                self.assertNotIn(forbidden, header)


class FilterTest(FilterExportFixture):
    def test_filtering_by_activity_type_narrows_both_page_and_export(self):
        rows = self.export_rows(fy=self.fy, activity_type="training")

        self.assertEqual(len(rows) - 1, 1)
        self.assertIn("training", rows[1])

    def test_filtering_by_executor_type_separates_partner_from_staff(self):
        partner_rows = self.export_rows(fy=self.fy, executor_type="partner")
        staff_rows = self.export_rows(fy=self.fy, executor_type="staff")

        self.assertEqual(len(partner_rows) - 1, 1)
        self.assertEqual(len(staff_rows) - 1, 2)

    def test_an_applied_filter_changes_the_pages_totals_too(self):
        body = (
            self.as_pl()
            .get(PL_URL, {"fy": self.fy, "activity_type": "training"})
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
