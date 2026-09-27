"""Salesforce ID and Evidence columns, and completed-last order, on every
planned activities table (owner, 2026-09-26).

"Add those columns on the all planned activities tables from My Plan pages
and Oversight pages, with all completed activities pushed to the bottom of
the table and uncompleted ones on top, arranged by date planned in ascending
order." Completed means evidence uploaded and Salesforce ID entered.

Held here: the rule and the words (apps.activities.completion_columns), that
My Plan, Team Oversight and Partner Monitoring apply them before paging, and
that every target table draws the two columns before Status with its actions
pinned.
"""

from __future__ import annotations

import re
from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase
from django.utils import timezone

from apps.accounts.models import StaffProfile, StaffSchoolAssignment
from apps.activities.completion_columns import (
    MISSING_BOTH,
    MISSING_EVIDENCE,
    MISSING_SF,
    NO_EVIDENCE,
    NOT_IN_SF,
    annotate,
    completed_last_key,
    completion_columns,
    completion_fields,
    completion_gap,
    evidence_label,
    expected_evidence,
    is_complete,
    is_officer_completed,
    sort_completed_last,
)
from apps.activities.models import Activity
from apps.core.fy import get_operational_fy
from apps.core.rbac import EdifyRole
from apps.evidence.models import EvidenceRecord
from apps.geography.models import District, Region
from apps.schools.models import School

User = get_user_model()
ROOT = Path(__file__).resolve().parents[2]
D1, D2, D3 = date(2026, 3, 2), date(2026, 3, 9), date(2026, 3, 16)


class RuleTest(SimpleTestCase):
    def test_completed_means_evidence_and_salesforce_id_are_in(self):
        for status in (
            "submitted_to_pl",
            "awaiting_ia_verification",
            "ia_verified",
            "accountant_confirmed",
            "completed",
            "closed",
        ):
            self.assertTrue(is_officer_completed(status), status)
        for status in (
            "planned",
            "scheduled",
            "rescheduled",
            "in_progress",
            "completion_started",
            "evidence_uploaded",
            "salesforce_id_required",
            "returned_by_pl",
            "",
            None,
        ):
            self.assertFalse(is_officer_completed(status), status)

    def test_open_by_date_first_then_completed_by_date(self):
        rows = [
            ("done-late", True, D3),
            ("open-undated", False, None),
            ("open-late", False, D3),
            ("done-early", True, D1),
            ("open-early", False, D1),
            ("done-undated", True, None),
            ("open-mid", False, D2),
        ]
        rows.sort(key=lambda r: completed_last_key(r[1], r[2]))
        self.assertEqual(
            [r[0] for r in rows],
            [
                "open-early",
                "open-mid",
                "open-late",
                "open-undated",
                "done-early",
                "done-late",
                "done-undated",
            ],
        )

    def test_complete_only_with_both_columns_green(self):
        both = {"salesforce_ok": True, "evidence_ok": True}
        self.assertTrue(is_complete("ia_verified", both))
        self.assertTrue(is_complete("submitted_to_pl", both))
        self.assertFalse(is_complete("scheduled", both))
        self.assertFalse(is_complete("ia_verified", {"salesforce_ok": True}))
        self.assertEqual(completion_gap("scheduled", {}), "")
        self.assertEqual(completion_gap("ia_verified", both), "")
        self.assertEqual(
            completion_gap("ia_verified", {"salesforce_ok": True}), MISSING_EVIDENCE
        )
        self.assertEqual(completion_gap("closed", {"evidence_ok": True}), MISSING_SF)
        self.assertEqual(completion_gap("completed", {}), MISSING_BOTH)
        # The complete action is for verified work only, with both in.
        self.assertTrue(completion_fields("ia_verified", both)["shows_complete"])
        self.assertFalse(completion_fields("submitted_to_pl", both)["shows_complete"])
        self.assertFalse(
            completion_fields("closed", {"salesforce_ok": True})["shows_complete"]
        )

    def test_the_form_is_the_visit_form_or_the_attendance(self):
        self.assertEqual(
            expected_evidence("school_visit"), ("visit_form", "Visit Form")
        )
        self.assertEqual(expected_evidence("core_visit"), ("visit_form", "Visit Form"))
        for kind in ("cluster_training", "in_school_training", "cluster_meeting"):
            self.assertEqual(expected_evidence(kind), ("attendance_form", "Attendance"))
        self.assertEqual(
            evidence_label("school_visit", {"visit_form", "photo"}), "Visit Form"
        )
        self.assertEqual(
            evidence_label("cluster_meeting", {"attendance_form"}), "Attendance"
        )
        # Other evidence is named, never reported as missing.
        self.assertEqual(
            evidence_label("cluster_meeting", {"meeting_minutes", "photo"}),
            "Meeting Minutes, Photo",
        )
        self.assertEqual(evidence_label("school_visit", set()), "")

    def test_sorting_items_keeps_ties_in_arrival_order(self):
        items = [
            SimpleNamespace(key="b", is_complete=False, planned_date=D1),
            SimpleNamespace(key="a", is_complete=False, planned_date=D1),
            SimpleNamespace(key="c", is_complete=True, planned_date=D1),
        ]
        sort_completed_last(items)
        self.assertEqual([i.key for i in items], ["b", "a", "c"])


class _Fixture(TestCase):
    def setUp(self):
        region = Region.objects.create(name="CC Region")
        self.district = District.objects.create(name="CC District", region=region)
        self.school = School.objects.create(
            school_id="CC-1",
            name="Column School",
            region=region,
            district=self.district,
            school_type="client",
        )
        self.cceo = User.objects.create_user(
            email="cc-cceo@t.org",
            name="Cora Field",
            roles=[EdifyRole.CCEO.value],
            active_role=EdifyRole.CCEO.value,
            password="x",
            is_active=True,
        )
        self.cceo_sp = StaffProfile.objects.create(user=self.cceo, title="CCEO")
        StaffSchoolAssignment.objects.create(
            staff=self.cceo_sp, school_id=self.school.id
        )

    def _act(self, day, *, status="scheduled", atype="school_visit", **extra):
        values = {
            "school": self.school,
            "activity_type": atype,
            "delivery_type": "staff",
            "status": status,
            "responsible_staff_id": self.cceo_sp.id,
            "fy": get_operational_fy(day),
            "planned_date": day,
        }
        values.update(extra)
        return Activity.objects.create(**values)

    def _evidence(self, activity, kind, **extra):
        return EvidenceRecord.objects.create(
            activity=activity, kind=kind, uri=f"{kind}.pdf", uploaded_by="u", **extra
        )


class ColumnValuesTest(_Fixture):
    def test_the_stored_id_and_the_uploaded_form(self):
        visit = self._act(D1, salesforce_activity_id="SVE-1234")
        self._evidence(visit, "visit_form")
        training = self._act(
            D1, atype="cluster_training", salesforce_activity_id=" TS-5678 "
        )
        self._evidence(training, "attendance_form")
        bare = self._act(D1)
        hidden = self._act(D1)
        self._evidence(hidden, "visit_form", quarantined=True)
        columns = completion_columns(
            [(a.id, a.activity_type) for a in (visit, training, bare, hidden)]
            + [(None, "school_visit")]
        )
        self.assertEqual(
            columns[visit.id],
            {
                "salesforce_id": "SVE-1234",
                "evidence_label": "Visit Form",
                "salesforce_ok": True,
                "evidence_ok": True,
            },
        )
        self.assertEqual(
            columns[training.id],
            {
                "salesforce_id": "TS-5678",
                "evidence_label": "Attendance",
                "salesforce_ok": True,
                "evidence_ok": True,
            },
        )
        # Blank reads NOT_IN_SF and NO_EVIDENCE on the page; a quarantined
        # file is not evidence, as completion counts it.
        empty = {
            "salesforce_id": "",
            "evidence_label": "",
            "salesforce_ok": False,
            "evidence_ok": False,
        }
        self.assertEqual(columns[bare.id], empty)
        self.assertEqual(columns[hidden.id], empty)
        self.assertNotIn(None, columns)

    def test_annotate_sets_the_columns_on_items(self):
        visit = self._act(D1, salesforce_activity_id="SVE-9")
        items = [
            SimpleNamespace(activity_id=visit.id, activity_type="school_visit"),
            SimpleNamespace(activity_id=None, activity_type="school_visit"),
        ]
        items[0].activity_status = "ia_verified"
        items[1].activity_status = "scheduled"
        annotate(items)
        self.assertEqual(
            (items[0].salesforce_id, items[0].evidence_label), ("SVE-9", "")
        )
        # Verified, but the visit form is not in: not complete, and says so.
        self.assertFalse(items[0].is_complete)
        self.assertEqual(items[0].completion_gap, MISSING_EVIDENCE)
        self.assertEqual((items[1].salesforce_id, items[1].evidence_label), ("", ""))
        self.assertEqual(items[1].completion_gap, "")


class MyPlanTest(_Fixture):
    def _days(self):
        """Three upcoming days inside one fiscal year: My Plan lists open
        work from today on, and reads one year at a time."""
        base = timezone.localdate() + timedelta(days=2)
        if get_operational_fy(base) != get_operational_fy(base + timedelta(days=2)):
            base += timedelta(days=3)
        return base, base + timedelta(days=1), base + timedelta(days=2)

    def test_the_school_visits_table_lists_open_work_first_with_the_columns(self):
        early, mid, late = self._days()
        done_early = self._act(
            early, status="ia_verified", salesforce_activity_id="SVE-1"
        )
        self._evidence(done_early, "visit_form")
        open_late = self._act(late)
        submitted = self._act(
            mid, status="submitted_to_pl", salesforce_activity_id="SVE-2"
        )
        open_early = self._act(early)
        open_mid = self._act(mid, status="in_progress")
        # Marked completed, but neither half is in: not complete.
        legacy = self._act(late, status="completed")
        self.client.force_login(self.cceo)
        response = self.client.get(
            "/my-plan", {"period": "fy", "fy": get_operational_fy(early)}
        )
        self.assertEqual(response.status_code, 200)
        rows = response.context["school_visits"]
        # Complete only with both columns green: the submitted visit without
        # its form and the legacy one sit with the open work, by date.
        self.assertEqual(
            [r["id"] for r in rows],
            [
                open_early.id,
                submitted.id,
                open_mid.id,
                open_late.id,
                legacy.id,
                done_early.id,
            ],
        )
        by_id = {r["id"]: r for r in rows}
        self.assertEqual(by_id[done_early.id]["salesforce_id"], "SVE-1")
        self.assertEqual(by_id[done_early.id]["evidence_label"], "Visit Form")
        self.assertTrue(by_id[done_early.id]["shows_complete"])
        self.assertEqual(by_id[submitted.id]["status_label"], MISSING_EVIDENCE)
        self.assertEqual(by_id[legacy.id]["status_label"], MISSING_BOTH)
        self.assertFalse(by_id[legacy.id]["shows_complete"])
        html = response.content.decode()
        for text in (
            ">Salesforce ID</th>",
            ">Evidence</th>",
            NOT_IN_SF,
            NO_EVIDENCE,
            "SVE-2",
        ):
            self.assertIn(text, html)


class OversightOrderTest(_Fixture):
    def test_team_oversight_tables_list_open_work_first_with_the_columns(self):
        from apps.frontend.views.oversight_views import (
            _partition_owner_groups_by_stream,
        )
        from apps.planning.oversight_service import (
            STAGE_STAFF_SCHEDULED,
            PlanningOversightItem,
        )

        done = self._act(D1, status="completed", salesforce_activity_id="SVE-7")
        self._evidence(done, "visit_form")
        late = self._act(D3)
        early = self._act(D1)
        # Verified, but neither half is in: not complete.
        half = self._act(D1, status="ia_verified")

        def item(activity):
            return PlanningOversightItem(
                stage=STAGE_STAFF_SCHEDULED,
                activity_id=activity.id,
                activity_type="school_visit",
                activity_status=activity.status,
                planned_date=activity.planned_date,
                operational_owner_id=self.cceo_sp.id,
                operational_owner_name="Cora Field",
                school_name="Column School",
                school_type="client",
            )

        groups = [
            {
                "id": self.cceo_sp.id,
                "name": "Cora Field",
                "items": [item(done), item(late), item(early), item(half)],
            }
        ]
        groups = _partition_owner_groups_by_stream(groups, self.cceo)
        visits = groups[0]["client_school_visits"]
        self.assertEqual(
            [i.activity_id for i in visits], [early.id, half.id, late.id, done.id]
        )
        self.assertEqual(visits[-1].salesforce_id, "SVE-7")
        self.assertTrue(visits[-1].shows_complete)
        self.assertEqual(visits[1].completion_gap, MISSING_BOTH)
        self.assertFalse(visits[1].shows_complete)

    def test_partner_monitoring_keeps_hand_backs_first_then_open_by_date(self):
        from apps.planning.partner_oversight_service import (
            STAGE_AWAITING_SCHEDULE,
            STAGE_RETURNED,
            STAGE_SCHEDULED,
            PartnerOversightItem,
            order_for_monitoring,
        )

        def item(key, stage, status="", day=None, school="S", activity=None):
            return PartnerOversightItem(
                stage=stage,
                partner_assignment_id=key,
                partner_activity_id=activity.id if activity else None,
                activity_type="school_visit",
                activity_status=status,
                scheduled_date=day,
                school_name=school,
            )

        # Submitted to IA with the Salesforce ID and the visit form: complete.
        delivered = self._act(
            D1,
            status="awaiting_ia_verification",
            delivery_type="partner",
            salesforce_activity_id="SVE-8",
        )
        self._evidence(delivered, "visit_form")
        # Submitted without either half: not complete, and says so.
        bare = self._act(D1, status="awaiting_ia_verification", delivery_type="partner")
        items = [
            item(
                "done",
                STAGE_SCHEDULED,
                "awaiting_ia_verification",
                D1,
                activity=delivered,
            ),
            item(
                "bare", STAGE_SCHEDULED, "awaiting_ia_verification", D1, activity=bare
            ),
            item("late", STAGE_SCHEDULED, "partner_scheduled", D3),
            item("undated", STAGE_AWAITING_SCHEDULE),
            item("returned", STAGE_RETURNED),
            item("early", STAGE_SCHEDULED, "partner_scheduled", D1),
        ]
        order_for_monitoring(items)
        self.assertEqual(
            [i.partner_assignment_id for i in items],
            ["returned", "bare", "early", "late", "undated", "done"],
        )
        by_key = {i.partner_assignment_id: i for i in items}
        self.assertEqual(by_key["bare"].completion_gap, MISSING_BOTH)
        self.assertEqual(by_key["done"].salesforce_id, "SVE-8")


class TemplateTest(SimpleTestCase):
    """Every planned activities table draws Salesforce ID and Evidence just
    before Status, from the one shared cell partial, and pins its actions."""

    TABLES = {
        "templates/partials/my_plan/school_visits.html": 1,
        "templates/partials/my_plan/cluster_trainings.html": 1,
        "templates/partials/my_plan/cluster_meetings.html": 1,
        "templates/partials/my_plan/core_school_visits.html": 1,
        "templates/partials/my_plan/core_school_trainings.html": 1,
        "templates/partials/my_plan/programme_activities.html": 1,
        "templates/partials/my_plan/programme_school_work.html": 1,
        "templates/partials/oversight/_officer_panel_body.html": 4,
        "templates/partials/oversight/cluster_activity_table.html": 1,
        "templates/partials/oversight/_core_work_table.html": 1,
        "templates/partials/oversight/partner_work_tables.html": 2,
        "templates/partials/dashboards/pl/_week_tables.html": 3,
    }
    #: Tables with no Actions column have nothing to pin.
    UNPINNED = {"templates/partials/oversight/_core_work_table.html"}
    #: Partner Monitoring draws its tables from one <table> in a loop.
    PINNED = {"templates/partials/oversight/partner_work_tables.html": 1}

    def test_the_columns_sit_before_status(self):
        for path, count in self.TABLES.items():
            source = (ROOT / path).read_text()
            with self.subTest(path=path):
                heads = re.findall(
                    r">Salesforce ID</th>\s*<th[^>]*>Evidence</th>\s*<th[^>]*>Status</th>",
                    source,
                )
                self.assertEqual(len(heads), count)
                if path not in self.UNPINNED:
                    self.assertEqual(
                        source.count("data-pinned-actions"),
                        self.PINNED.get(path, count),
                    )

    def test_the_cells_come_from_one_partial(self):
        rows = [
            *[p for p in self.TABLES if "partner_work_tables" not in p],
            "templates/partials/oversight/partner_school_row.html",
            "templates/partials/oversight/partner_work_row.html",
        ]
        for path in rows:
            with self.subTest(path=path):
                self.assertIn(
                    '{% include "components/completion_cells.html"',
                    (ROOT / path).read_text(),
                )
        cells = (ROOT / "templates/components/completion_cells.html").read_text()
        self.assertIn(NOT_IN_SF, cells)
        self.assertIn(NO_EVIDENCE, cells)
