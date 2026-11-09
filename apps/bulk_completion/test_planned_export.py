"""Bulk completion starts from the planned work (owner, 2026-11-09).

Pinned here:

  1. Each upload has its own columns: the School Visits file carries no
     training_sf_id, the Trainings file no visit_sf_id.
  2. "Export Planned Activities" writes the activities already scheduled in
     the chosen period — a month, a date range, a quarter or a financial year
     (1 October to 30 September) — each with its own Planned Activity ID,
     school, scheduled date, responsible staff and Programme Lead. Open work
     only, unless completed work is asked for to reconcile.
  3. It narrows by staff member, Programme Lead, district and activity type,
     and the page says how many activities match before the download.
  4. The exported file, filled in and uploaded, completes exactly the
     activities it lists: two visits to one school stay two visits, and a
     line left blank is skipped, not refused.
"""

from __future__ import annotations

from datetime import date, timedelta
from io import BytesIO

import openpyxl
from django.core.files.uploadedfile import SimpleUploadedFile

from apps.activities.models import ClusterActivityAttendance
from apps.bulk_completion.apply import apply_batch
from apps.bulk_completion.models import RowStatus
from apps.bulk_completion.staging import stage_upload
from apps.bulk_completion.test_bulk_visits import BulkFixture
from apps.core.fy import get_operational_fy
from apps.geography.models import District
from apps.schools.models import School

EXPORT = "/uploads/bulk-completion/{kind}/template"
PAGE = "/uploads/bulk-completion/{kind}"


def _fy() -> str:
    return get_operational_fy()


def _october(day: int = 15) -> date:
    return date(int(_fy()) - 1, 10, day)


def _january(day: int = 15) -> date:
    return date(int(_fy()), 1, day)


def _rows(response) -> list[tuple]:
    sheet = openpyxl.load_workbook(BytesIO(response.content)).worksheets[0]
    return list(sheet.iter_rows(values_only=True))


def _by_heading(rows) -> list[dict]:
    headings = rows[0]
    return [dict(zip(headings, row)) for row in rows[1:]]


class ExportFixture(BulkFixture):
    def _planned(self, day, owner=None, **extra):
        return self._visit(owner=owner, planned_date=day, fy=_fy(), **extra)

    def _export(self, kind="visit", **query):
        response = self.as_user(self.ia_user).get(EXPORT.format(kind=kind), query)
        self.assertEqual(response.status_code, 200)
        return _rows(response)

    def _ids(self, rows) -> set:
        return {row["planned_activity_id"] for row in _by_heading(rows)}


class EachUploadCarriesOnlyItsOwnIds(ExportFixture):
    def test_the_visit_export_has_no_training_id_column(self):
        headings = self._export(period="fy", fy=_fy())[0]
        self.assertNotIn("training_sf_id", headings)
        for wanted in (
            "planned_activity_id",
            "School ID",
            "School Name",
            "Planned Activity",
            "Scheduled Date",
            "Responsible Staff",
            "Programme Lead",
            "visit_sf_id",
            "completed_date",
        ):
            self.assertIn(wanted, headings)

    def test_the_training_export_has_no_visit_id_column(self):
        headings = self._export("training", period="fy", fy=_fy())[0]
        self.assertNotIn("visit_sf_id", headings)
        for wanted in (
            "planned_activity_id",
            "School ID",
            "Training Name",
            "Delivery Mode",
            "training_sf_id",
            "completed_date",
            "teachers_trained",
            "school_leaders_trained",
        ):
            self.assertIn(wanted, headings)

    def test_a_visit_file_without_a_training_id_column_uploads(self):
        visit = self._planned(_october())
        body = "planned_activity_id,school_id,visit_sf_id,completed_date\n"
        body += f"{visit.id},REV-1,SVE-61001,{self.done_on.isoformat()}\n"
        batch = stage_upload(
            SimpleUploadedFile("v.csv", body.encode(), "text/csv"),
            "visit",
            self.ia_user,
        )
        self.assertEqual(self._statuses(batch), [RowStatus.READY])

    def test_a_training_file_in_the_visit_upload_is_named_as_such(self):
        from apps.core.exceptions import BadRequest

        body = (
            "planned_activity_id,school_id,training_sf_id,completed_date\n"
            f"x,REV-1,TS-1,{self.done_on.isoformat()}\n"
        )
        with self.assertRaises(BadRequest) as refused:
            stage_upload(
                SimpleUploadedFile("t.csv", body.encode(), "text/csv"),
                "visit",
                self.ia_user,
            )
        self.assertIn("Trainings upload", str(refused.exception.detail))


class TheExportFollowsThePeriod(ExportFixture):
    def setUp(self):
        super().setUp()
        self.october = self._planned(_october())
        self.january = self._planned(_january())

    def test_a_month_exports_only_that_months_visits_with_their_ids(self):
        rows = self._export(period="month", fy=_fy(), month="10")
        self.assertEqual(self._ids(rows), {self.october.id})
        line = _by_heading(rows)[0]
        self.assertEqual(line["School ID"], "REV-1")
        self.assertEqual(line["School Name"], "Alpha Primary")
        self.assertEqual(line["Responsible Staff"], "James")
        self.assertEqual(line["Programme Lead"], "Lead Lydia")
        self.assertEqual(line["Scheduled Date"].date(), _october())

    def test_a_quarter_follows_the_financial_calendar(self):
        self.assertEqual(
            self._ids(self._export(period="quarter", fy=_fy(), quarter="Q1")),
            {self.october.id},
        )
        self.assertEqual(
            self._ids(self._export(period="quarter", fy=_fy(), quarter="Q2")),
            {self.january.id},
        )

    def test_a_date_range_includes_both_its_ends(self):
        rows = self._export(
            period="range",
            start=_october().isoformat(),
            end=_january().isoformat(),
        )
        self.assertEqual(self._ids(rows), {self.october.id, self.january.id})

    def test_the_financial_year_runs_october_to_september(self):
        before = self._planned(date(int(_fy()) - 1, 9, 30))
        rows = self._export(period="fy", fy=_fy())
        self.assertEqual(self._ids(rows), {self.october.id, self.january.id})
        self.assertNotIn(before.id, self._ids(rows))

    def test_completed_work_is_left_out_unless_asked_for(self):
        done = self._planned(
            _october(20), status="ia_verified", salesforce_activity_id="SVE-61002"
        )
        self.assertNotIn(done.id, self._ids(self._export(period="fy", fy=_fy())))
        self.assertIn(
            done.id,
            self._ids(self._export(period="fy", fy=_fy(), completed="1")),
        )

    def test_cancelled_work_is_never_exported(self):
        gone = self._planned(_october(21), status="cancelled")
        rows = self._export(period="fy", fy=_fy(), completed="1")
        self.assertNotIn(gone.id, self._ids(rows))


class TheExportNarrowsByFilter(ExportFixture):
    def test_by_staff_member_in_either_id_space(self):
        james = self._planned(_october())
        mary = self._planned(
            _october(), owner=self.mary_user.id, school=self.mary_school
        )
        rows = self._export(period="fy", fy=_fy(), staff=self.mary.id)
        self.assertEqual(self._ids(rows), {mary.id})
        self.assertNotIn(james.id, self._ids(rows))

    def test_by_programme_lead_reads_their_team(self):
        mine = self._planned(_october())
        rival = self._planned(_october(), owner=self.rival.id, school=self.rival_school)
        rows = self._export(period="fy", fy=_fy(), lead=self.pl_user.id)
        self.assertEqual(self._ids(rows), {mine.id})
        rows = self._export(period="fy", fy=_fy(), lead=self.rival_pl_user.id)
        self.assertEqual(self._ids(rows), {rival.id})

    def test_by_district(self):
        elsewhere = District.objects.create(name="Other District", region=self.region)
        far = School.objects.create(
            school_id="FAR-1",
            name="Far Primary",
            region=self.region,
            district=elsewhere,
        )
        near = self._planned(_october())
        away = self._planned(_october(), school=far)
        rows = self._export(period="fy", fy=_fy(), district=elsewhere.id)
        self.assertEqual(self._ids(rows), {away.id})
        self.assertNotIn(near.id, self._ids(rows))

    def test_by_activity_type(self):
        visit = self._planned(_october())
        follow_up = self._planned(_october(), activity_type="follow_up_visit")
        rows = self._export(period="fy", fy=_fy(), type="follow_up_visit")
        self.assertEqual(self._ids(rows), {follow_up.id})
        self.assertNotIn(visit.id, self._ids(rows))

    def test_the_page_counts_the_matches_before_the_download(self):
        self._planned(_october())
        self._planned(_october(22))
        self._planned(_january())
        page = self.as_user(self.ia_user).get(
            PAGE.format(kind="visit"), {"period": "month", "fy": _fy(), "month": "10"}
        )
        self.assertContains(page, 'data-bulk-matches="2"')
        self.assertContains(page, "period=month")

    def test_a_reversed_date_range_is_refused_with_a_reason(self):
        page = self.as_user(self.ia_user).get(
            PAGE.format(kind="visit"),
            {"period": "range", "start": "2027-02-01", "end": "2027-01-01"},
        )
        self.assertContains(page, "The start date is after the end date.")


class TheFilledExportCompletesExactlyItsActivities(ExportFixture):
    def _filled(self, rows, fill: dict) -> SimpleUploadedFile:
        """The exported sheet with some lines filled in, as an uploader would."""
        book = openpyxl.Workbook()
        sheet = book.active
        headings = list(rows[0])
        sheet.append(headings)
        for row in rows[1:]:
            values = list(row)
            for heading, value in fill.get(row[0], {}).items():
                values[headings.index(heading)] = value
            sheet.append(values)
        buffer = BytesIO()
        book.save(buffer)
        return SimpleUploadedFile("planned.xlsx", buffer.getvalue())

    def test_two_visits_to_one_school_stay_two_and_a_blank_line_is_skipped(self):
        first = self._planned(_october(5))
        second = self._planned(_october(25))
        rows = self._export(period="month", fy=_fy(), month="10")
        done = min(self.done_on, _october(5) + timedelta(days=1))
        batch = stage_upload(
            self._filled(
                rows,
                {first.id: {"visit_sf_id": "SVE-61010", "completed_date": done}},
            ),
            "visit",
            self.ia_user,
        )
        outcome = dict(batch.rows.values_list("activity_id", "status"))
        self.assertEqual(outcome[first.id], RowStatus.READY)
        self.assertEqual(outcome[second.id], RowStatus.NOT_FILLED)

        apply_batch(batch, self.ia_user)

        first.refresh_from_db()
        second.refresh_from_db()
        self.assertEqual(first.salesforce_activity_id, "SVE-61010")
        self.assertEqual(first.status, "ia_verified")
        self.assertEqual(second.status, "scheduled", "the other visit is untouched")
        self.assertFalse(second.salesforce_activity_id)

    def test_a_training_export_lists_each_invited_school_once(self):
        training = self._visit(
            activity_type="cluster_training",
            school=None,
            cluster=self.cluster,
            planned_date=_october(),
            fy=_fy(),
        )
        for ref, name in (("INV-A", "Invited A"), ("INV-B", "Invited B")):
            school = School.objects.create(
                school_id=ref,
                name=name,
                region=self.region,
                district=self.district,
                cluster_id=self.cluster.id,
            )
            ClusterActivityAttendance.objects.create(
                activity=training, school=school, attended=False
            )
        lines = _by_heading(self._export("training", period="fy", fy=_fy()))
        mine = [line for line in lines if line["planned_activity_id"] == training.id]
        self.assertEqual({line["School ID"] for line in mine}, {"INV-A", "INV-B"})
        self.assertEqual({line["Delivery Mode"] for line in mine}, {"Cluster"})
        self.assertEqual({line["Cluster"] for line in mine}, {"Mukono North"})
