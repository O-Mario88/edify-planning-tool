"""The Programme Lead's This Week view (owner, 2026-09-26).

"The PL needs to know where their team members are working, what schools they
are visiting and what training they have that week, so he can follow up with
them … and what the partners have done over the week for strict monitoring."
Last week's unfinished work comes first, because it is the freshest follow-up.

Then (same day): each officer's tab has two lists, Overdue and Due this week,
each as the School Visits, Group Trainings and Cluster Meetings tables of "What
needs you now", with the same columns, and one action per row — Verify when
the officer has completed it (evidence uploaded and Salesforce ID entered),
Send to <officer> when they have not.

Held here: whose work each tab shows (the lead's own team, never another
lead's), how a day is read (the past-due rule's), what is overdue, which
action each row offers and that each action's endpoint accepts exactly the
rows it is offered on, leave on the grid, the partners' week, and the old
Today doors.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.utils import timezone

from apps.accounts.models import (
    Leave,
    StaffProfile,
    StaffSchoolAssignment,
    StaffSupervisorAssignment,
)
from apps.activities.models import Activity
from apps.analytics.pl_week_service import (
    DUE_THIS_WEEK,
    EVERYONE,
    ME,
    OVERDUE,
    PARTNERS,
    build_week,
    kind_of,
    monday_of,
    resolve_week,
    table_of,
    week_status,
)
from apps.core.rbac import EdifyRole
from apps.geography.models import District, Region
from apps.notifications.models import Notification
from apps.schools.models import School

User = get_user_model()
LOCMEM = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "pl-week-tests",
    }
}
# A Thursday, so the week has days behind it and days ahead of it.
THURSDAY = date(2026, 9, 24)
MONDAY = date(2026, 9, 21)
LAST_MONDAY = date(2026, 9, 14)


class WeekRulesTest(TestCase):
    """The pure rules: which week, and what each status asks of the lead."""

    def test_a_week_is_named_by_any_day_in_it_and_nonsense_is_this_week(self):
        self.assertEqual(resolve_week("2026-09-24", THURSDAY), MONDAY)
        self.assertEqual(resolve_week("2026-09-14", THURSDAY), LAST_MONDAY)
        self.assertEqual(resolve_week("", THURSDAY), MONDAY)
        self.assertEqual(resolve_week("not-a-date", THURSDAY), MONDAY)
        self.assertEqual(resolve_week("1990-01-01", THURSDAY), MONDAY)

    def test_completed_by_the_officer_asks_verify_otherwise_send(self):
        past, today, ahead = MONDAY, THURSDAY, THURSDAY + timedelta(days=1)

        def ask(status, day=past):
            state = week_status(status, day, today)
            return state["key"], state["action"]

        # Completing means evidence uploaded and Salesforce ID entered, which
        # hands the work to the lead.
        self.assertEqual(ask("submitted_to_pl"), ("awaiting_you", "verify"))
        # Not completed from the officer's side: the lead sends to them.
        self.assertEqual(ask("scheduled"), ("past_due", "send"))
        self.assertEqual(ask("rescheduled"), ("past_due", "send"))
        self.assertEqual(ask("scheduled", today), ("today", "send"))
        self.assertEqual(ask("scheduled", ahead), ("scheduled", "send"))
        self.assertEqual(ask("in_progress"), ("started", "send"))
        self.assertEqual(ask("evidence_uploaded"), ("not_submitted", "send"))
        self.assertEqual(ask("salesforce_id_required"), ("sf_missing", "send"))
        self.assertEqual(ask("returned_by_pl"), ("returned", "send"))
        # Nothing left to ask.
        for status in ("ia_verified", "completed", "closed", "accountant_confirmed"):
            self.assertEqual(ask(status), ("verified", "none"))
        self.assertEqual(ask("awaiting_ia_verification"), ("with_ia", "none"))

    def test_the_three_tables_group_work_as_what_needs_you_now_does(self):
        self.assertEqual(table_of("school_visit"), "visits")
        self.assertEqual(table_of("cluster_training"), "trainings")
        self.assertEqual(table_of("in_school_training"), "trainings")
        self.assertEqual(table_of("cluster_meeting"), "meetings")
        self.assertEqual(table_of("cluster_meeting_ssa_review"), "meetings")
        # Every other type sits with the visits, as it does there.
        self.assertEqual(table_of("programme_event"), "visits")
        self.assertEqual(kind_of("cluster_meeting"), "meeting")
        self.assertEqual(kind_of("programme_event"), "other")


@override_settings(CACHES=LOCMEM)
class PLWeekTest(TestCase):
    def setUp(self):
        region = Region.objects.create(name="Week Region")
        self.district = District.objects.create(name="Week District", region=region)
        self.pl, self.pl_sp = self._staff("wk-pl@t.org", "Grace Lead", "pl")
        self.a1, self.a1_sp = self._staff("wk-a1@t.org", "Amos Field", "cceo")
        self.a2, self.a2_sp = self._staff("wk-a2@t.org", "Beth Field", "cceo")
        StaffSupervisorAssignment.objects.create(
            supervisor=self.pl_sp, supervisee=self.a1_sp
        )
        StaffSupervisorAssignment.objects.create(
            supervisor=self.pl_sp, supervisee=self.a2_sp
        )
        self.other_pl, self.other_pl_sp = self._staff(
            "wk-pl2@t.org", "Other Lead", "pl"
        )
        self.b1, self.b1_sp = self._staff("wk-b1@t.org", "Stranger Field", "cceo")
        StaffSupervisorAssignment.objects.create(
            supervisor=self.other_pl_sp, supervisee=self.b1_sp
        )
        self.s1 = self._school("W-1", "Hill School")
        self.s2 = self._school("W-2", "River School")
        self.s3 = self._school("W-3", "Stranger School")
        for staff, school in (
            (self.a1_sp, self.s1),
            (self.a2_sp, self.s2),
            (self.b1_sp, self.s3),
        ):
            StaffSchoolAssignment.objects.create(staff=staff, school_id=school.id)

    # ── fixtures ─────────────────────────────────────────────────────────────
    def _staff(self, email, name, kind):
        role = (
            EdifyRole.COUNTRY_PROGRAM_LEAD.value
            if kind == "pl"
            else EdifyRole.CCEO.value
        )
        user = User.objects.create_user(
            email=email,
            name=name,
            roles=[role],
            active_role=role,
            password="x",
            is_active=True,
        )
        return user, StaffProfile.objects.create(user=user, title=role)

    def _school(self, code, name):
        return School.objects.create(
            school_id=code,
            name=name,
            region=self.district.region,
            district=self.district,
        )

    def _act(
        self, staff, school, day, *, atype="school_visit", status="scheduled", **extra
    ):
        values = {
            "school": school,
            "activity_type": atype,
            "delivery_type": "staff",
            "status": status,
            "responsible_staff_id": staff.id,
            "fy": "2026",
            "planned_date": day,
        }
        values.update(extra)
        return Activity.objects.create(**values)

    def _week(self, who="", week=None, today=THURSDAY, listing=""):
        return build_week(
            self.pl, fy="2026", who=who, week=week, today=today, listing=listing
        )

    def _table(self, person, key):
        table = next(t for t in person["tables"] if t["key"] == key)
        return list(table["rows"])

    # ── Who ──────────────────────────────────────────────────────────────────
    def test_tabs_are_everyone_you_each_officer_then_partners(self):
        week = self._week()
        self.assertEqual(week["who"], EVERYONE)
        self.assertEqual(
            [t["label"] for t in week["tabs"]],
            ["Everyone", "Me", "Amos Field", "Beth Field", "Partners"],
        )
        self.assertEqual(
            [p["name"] for p in week["people"]], ["You", "Amos Field", "Beth Field"]
        )
        # An unknown or another lead's officer falls back to Everyone.
        self.assertEqual(self._week(who=self.b1_sp.id)["who"], EVERYONE)

    def test_another_lead_s_officer_never_appears(self):
        self._act(self.b1_sp, self.s3, MONDAY)
        self._act(self.a1_sp, self.s1, MONDAY)
        week = self._week()
        where = [
            r["where"]
            for p in week["people"]
            for cell in p["cells"]
            for r in cell["rows"]
        ]
        self.assertEqual(where, ["Hill School"])

    # ── The grid ─────────────────────────────────────────────────────────────
    def test_each_day_shows_where_each_person_is_working(self):
        self._act(self.a1_sp, self.s1, MONDAY, status="completed")
        self._act(self.a1_sp, self.s1, THURSDAY, atype="cluster_training")
        self._act(self.pl_sp, self.s2, MONDAY + timedelta(days=1))
        week = self._week()
        self.assertEqual(
            [d["label"] for d in week["days"]], ["Mon", "Tue", "Wed", "Thu", "Fri"]
        )
        amos = next(p for p in week["people"] if p["key"] == self.a1_sp.id)
        monday, _, _, thursday, _ = amos["cells"]
        self.assertEqual(
            [(r["where"], r["kind"], r["state"]) for r in monday["rows"]],
            [("Hill School", "visit", "verified")],
        )
        self.assertEqual(
            [(r["kind"], r["state"]) for r in thursday["rows"]], [("training", "today")]
        )
        self.assertTrue(thursday["is_today"])
        self.assertEqual((amos["planned"], amos["done"]), (2, 1))
        me = week["people"][0]
        self.assertEqual(me["cells"][1]["rows"][0]["where"], "River School")

    def test_weekend_columns_appear_only_when_someone_works_on_them(self):
        self.assertEqual(len(self._week()["days"]), 5)
        self._act(self.a2_sp, self.s2, MONDAY + timedelta(days=5))
        self.assertEqual(len(self._week()["days"]), 7)

    def test_a_day_is_the_planned_date_else_the_scheduled_timestamp(self):
        moment = timezone.make_aware(datetime.combine(MONDAY, datetime.min.time()))
        self._act(self.a1_sp, self.s1, None, scheduled_date=moment.replace(hour=9))
        # Planned date wins over a scheduled timestamp in another week.
        self._act(
            self.a1_sp,
            self.s1,
            MONDAY + timedelta(days=14),
            scheduled_date=moment.replace(hour=9),
        )
        amos = next(p for p in self._week()["people"] if p["key"] == self.a1_sp.id)
        self.assertEqual(amos["planned"], 1)
        self.assertEqual(len(amos["cells"][0]["rows"]), 1)

    def test_released_and_partner_delivered_work_is_not_an_officer_s_week(self):
        for status in ("cancelled", "rejected", "deferred", "not_planned"):
            self._act(self.a1_sp, self.s1, MONDAY, status=status)
        self._act(self.a1_sp, self.s1, MONDAY, delivery_type="partner")
        amos = next(p for p in self._week()["people"] if p["key"] == self.a1_sp.id)
        self.assertEqual(amos["planned"], 0)

    def test_approved_leave_shows_on_its_days(self):
        Leave.objects.create(
            staff=self.a2_sp,
            type="personal_time_off",
            start_date="2026-09-23",
            end_date="2026-09-24",
            days=2,
            status="approved",
        )
        Leave.objects.create(
            staff=self.a1_sp,
            type="personal_time_off",
            start_date="2026-09-22",
            end_date="2026-09-22",
            days=1,
            status="pending",
        )
        week = self._week(who=self.a2_sp.id)
        beth = next(p for p in week["people"] if p["key"] == self.a2_sp.id)
        self.assertEqual(
            [c["on_leave"] for c in beth["cells"]], [False, False, True, True, False]
        )
        self.assertEqual(week["person"]["leave"], ["Wed 23 Sep – Thu 24 Sep"])
        amos = next(p for p in week["people"] if p["key"] == self.a1_sp.id)
        self.assertFalse(any(c["on_leave"] for c in amos["cells"]))

    # ── Overdue and Due this week ────────────────────────────────────────────
    def test_an_officer_s_tab_opens_on_overdue_with_the_three_tables(self):
        visit = self._act(self.a1_sp, self.s1, LAST_MONDAY)
        self._act(self.a1_sp, self.s1, LAST_MONDAY, atype="cluster_training")
        self._act(self.a1_sp, self.s1, LAST_MONDAY, atype="cluster_meeting")
        self._act(self.a1_sp, self.s1, MONDAY)
        person = self._week(who=self.a1_sp.id)["person"]
        self.assertEqual(person["listing"], OVERDUE)
        self.assertEqual(
            [(t["title"], t["count"]) for t in person["tables"]],
            [("School Visits", 1), ("Group Trainings", 1), ("Cluster Meetings", 1)],
        )
        self.assertEqual(
            [(item["key"], item["count"]) for item in person["lists"]],
            [(OVERDUE, 3), (DUE_THIS_WEEK, 1)],
        )
        row = self._table(person, "visits")[0]
        # "What needs you now"'s own row: the same columns' data.
        self.assertEqual(row["id"], visit.id)
        self.assertEqual(row["school_name"], "Hill School")
        self.assertEqual(row["owner"], "Amos Field")
        self.assertIn("budget_total", row)
        self.assertEqual((row["status_label"], row["action"]), ("Past Due", "send"))
        self.assertTrue(row["is_overdue"])

    def test_with_nothing_overdue_the_tab_opens_on_the_week(self):
        self._act(self.a2_sp, self.s2, THURSDAY + timedelta(days=1))
        person = self._week(who=self.a2_sp.id)["person"]
        self.assertEqual(person["listing"], DUE_THIS_WEEK)
        row = self._table(person, "visits")[0]
        self.assertEqual((row["status_label"], row["action"]), ("Scheduled", "send"))
        self.assertFalse(row["is_overdue"])
        # The other list stays one click away.
        overdue = self._week(who=self.a2_sp.id, listing=OVERDUE)["person"]
        self.assertEqual(overdue["listing"], OVERDUE)
        self.assertEqual(sum(t["count"] for t in overdue["tables"]), 0)

    def test_verify_when_the_officer_has_completed_it_send_when_not(self):
        rows = {
            status: self._act(self.a1_sp, self.s1, MONDAY, status=status)
            for status in (
                "submitted_to_pl",
                "salesforce_id_required",
                "evidence_uploaded",
                "scheduled",
                "ia_verified",
                "awaiting_ia_verification",
            )
        }
        person = self._week(who=self.a1_sp.id, listing=DUE_THIS_WEEK)["person"]
        action = {r["id"]: r["action"] for r in self._table(person, "visits")}
        self.assertEqual(action[rows["submitted_to_pl"].id], "verify")
        for status in ("salesforce_id_required", "evidence_uploaded", "scheduled"):
            self.assertEqual(action[rows[status].id], "send", status)
        # Completed work is off the list altogether.
        self.assertNotIn(rows["ia_verified"].id, action)
        self.assertNotIn(rows["awaiting_ia_verification"].id, action)
        self.assertEqual(person["send_name"], "Amos")

    def test_completed_work_leaves_the_lists_and_the_figures_keep_it(self):
        verified = self._act(self.a1_sp, self.s1, MONDAY, status="ia_verified")
        with_ia = self._act(
            self.a1_sp, self.s1, MONDAY, status="awaiting_ia_verification"
        )
        open_ = self._act(self.a1_sp, self.s1, THURSDAY + timedelta(days=1))
        week = self._week(who=self.a1_sp.id, listing=DUE_THIS_WEEK)
        person = week["person"]
        self.assertEqual([r["id"] for r in self._table(person, "visits")], [open_.id])
        self.assertEqual(person["lists"][1]["count"], 1)
        self.assertEqual((person["planned"], person["closed"]), (3, 2))
        # Verifying one takes it off the list on the next read.
        open_.status = "ia_verified"
        open_.save(update_fields=["status"])
        person = self._week(who=self.a1_sp.id, listing=DUE_THIS_WEEK)["person"]
        self.assertEqual(self._table(person, "visits"), [])
        # The week board still shows where the work was done.
        amos = next(p for p in week["people"] if p["key"] == self.a1_sp.id)
        board = {r["id"] for cell in amos["cells"] for r in cell["rows"]}
        self.assertTrue({verified.id, with_ia.id} <= board)

    def test_each_row_shows_its_salesforce_id_and_the_form_uploaded(self):
        from apps.evidence.models import EvidenceRecord

        def evidence(activity, kind, **extra):
            EvidenceRecord.objects.create(
                activity=activity,
                kind=kind,
                uri=f"{kind}.pdf",
                uploaded_by="u",
                **extra,
            )

        visit = self._act(
            self.a1_sp, self.s1, MONDAY, salesforce_activity_id="SVE-1234"
        )
        evidence(visit, "visit_form")
        training = self._act(
            self.a1_sp,
            self.s1,
            MONDAY,
            atype="cluster_training",
            salesforce_activity_id="TS-5678",
        )
        evidence(training, "attendance_form")
        meeting = self._act(self.a1_sp, self.s1, MONDAY, atype="cluster_meeting")
        evidence(meeting, "meeting_minutes")
        bare = self._act(self.a1_sp, self.s1, MONDAY)
        hidden = self._act(self.a1_sp, self.s1, MONDAY)
        evidence(hidden, "visit_form", quarantined=True)
        person = self._week(who=self.a1_sp.id, listing=DUE_THIS_WEEK)["person"]
        rows = {
            r["id"]: (r["salesforce_id"], r["evidence_label"])
            for key in ("visits", "trainings", "meetings")
            for r in self._table(person, key)
        }
        self.assertEqual(rows[visit.id], ("SVE-1234", "Visit Form"))
        self.assertEqual(rows[training.id], ("TS-5678", "Attendance"))
        # Other evidence is named, never reported as missing.
        self.assertEqual(rows[meeting.id], ("", "Meeting Minutes"))
        # Blank reads "Not in SF" and "No Evidence Uploaded" on the page; a
        # quarantined file is not evidence, as completion counts it.
        self.assertEqual(rows[bare.id], ("", ""))
        self.assertEqual(rows[hidden.id], ("", ""))

    def test_every_row_past_its_day_is_overdue_whoever_it_waits_on(self):
        late = self._act(self.a1_sp, self.s1, MONDAY)
        waiting = self._act(self.a1_sp, self.s1, MONDAY, status="submitted_to_pl")
        today = self._act(self.a1_sp, self.s1, THURSDAY)
        ahead = self._act(self.a1_sp, self.s1, THURSDAY + timedelta(days=1))
        person = self._week(who=self.a1_sp.id, listing=DUE_THIS_WEEK)["person"]
        overdue = {r["id"]: r["is_overdue"] for r in self._table(person, "visits")}
        self.assertEqual(
            overdue,
            {late.id: True, waiting.id: True, today.id: False, ahead.id: False},
        )

    def test_overdue_is_last_week_s_work_not_yet_verified(self):
        kept = {
            status: self._act(self.a1_sp, self.s1, LAST_MONDAY, status=status)
            for status in ("scheduled", "in_progress", "submitted_to_pl")
        }
        for status in (
            "completed",
            "ia_verified",
            "awaiting_ia_verification",
            "cancelled",
        ):
            self._act(self.a1_sp, self.s1, LAST_MONDAY, status=status)
        # Older than last week: the backlog's, under All overdue plans.
        self._act(self.a1_sp, self.s1, LAST_MONDAY - timedelta(days=3))
        week = self._week(who=self.a1_sp.id)
        rows = self._table(week["person"], "visits")
        self.assertEqual({r["id"] for r in rows}, {a.id for a in kept.values()})
        self.assertEqual(week["overdue_total"], 3)
        amos = next(p for p in week["people"] if p["key"] == self.a1_sp.id)
        self.assertEqual(amos["overdue_count"], 3)
        tab = next(t for t in week["tabs"] if t["key"] == self.a1_sp.id)
        self.assertEqual(tab["count"], 3)

    def test_the_lead_s_own_rows_keep_their_own_menu(self):
        self._act(self.pl_sp, self.s2, LAST_MONDAY)
        person = self._week(who=ME)["person"]
        row = self._table(person, "visits")[0]
        self.assertTrue(row["is_own"])
        self.assertEqual(row["action"], "own")
        self.assertEqual(person["send_name"], "")

    def test_a_reminder_already_sent_says_so_instead_of_sending_twice(self):
        activity = self._act(self.a1_sp, self.s1, MONDAY)
        Notification.objects.create(
            recipient_id=self.a1_sp.id,
            source_event_type="pl_activity_overdue_reminder",
            context_type="activity",
            context_id=activity.id,
            title="Action Required",
            body="Past due",
        )
        person = self._week(who=self.a1_sp.id, listing=DUE_THIS_WEEK)["person"]
        row = self._table(person, "visits")[0]
        self.assertEqual(row["action"], "sent")
        self.assertEqual(row["sent_on"], timezone.localdate())

    def test_work_beyond_this_week_is_not_offered_a_reminder(self):
        # The week arrows reach ahead; Send to never does.
        next_monday = monday_of(timezone.localdate()) + timedelta(days=7)
        self._act(self.a1_sp, self.s1, next_monday)
        person = build_week(
            self.pl,
            fy="2026",
            who=self.a1_sp.id,
            week=next_monday.isoformat(),
            listing=DUE_THIS_WEEK,
        )["person"]
        self.assertEqual(self._table(person, "visits")[0]["action"], "none")

    def test_another_week_is_overdue_from_the_week_before_it(self):
        self._act(self.a1_sp, self.s1, LAST_MONDAY - timedelta(days=7))
        week = self._week(who=self.a1_sp.id, week=LAST_MONDAY.isoformat())
        self.assertEqual(week["start"], LAST_MONDAY)
        self.assertFalse(week["is_current"])
        self.assertEqual(week["person"]["lists"][0]["count"], 1)
        self.assertEqual(week["overdue_label"], "Overdue from the week of 7 Sep")
        self.assertIn("week=2026-09-07", week["previous_url"])
        self.assertNotIn("week=", week["next_url"])

    # ── Partners ─────────────────────────────────────────────────────────────
    def _partner_item(self, **values):
        item = {
            "partner_id": "p1",
            "partner_name": "Light Partners",
            "is_scheduled": True,
            "scheduled_date": MONDAY,
            "schedule_by_date": None,
            "execution_status": "Not Started",
            "ia_status_label": "—",
            "risks": [],
            "school_name": "Hill School",
            "cluster_name": "",
            "district": "Week District",
            "training_name": "",
            "activity_type": "school_visit",
            "responsible_cceo_name": "Amos Field",
            "next_action": "Execute and upload evidence",
            "partner_assignment_id": "pa-1",
        }
        item.update(values)
        return SimpleNamespace(**item)

    def test_partners_show_the_week_then_what_is_still_late_exceptions_first(self):
        items = [
            self._partner_item(execution_status="Evidence Submitted"),
            self._partner_item(scheduled_date=MONDAY + timedelta(days=1)),
            self._partner_item(execution_status="In Progress"),
            self._partner_item(scheduled_date=THURSDAY + timedelta(days=1)),
            self._partner_item(
                scheduled_date=LAST_MONDAY,
                risks=[{"key": "partner_delivery_overdue"}],
            ),
            # Before the week and not late: not this page's business.
            self._partner_item(
                scheduled_date=LAST_MONDAY, execution_status="Evidence Submitted"
            ),
            self._partner_item(
                partner_id="p2",
                partner_name="Calm Partners",
                is_scheduled=False,
                scheduled_date=None,
                schedule_by_date=LAST_MONDAY,
                risks=[{"key": "partner_schedule_overdue"}],
            ),
            self._partner_item(
                partner_id="p3",
                partner_name="Quiet Partners",
                execution_status="Evidence Submitted",
                ia_status_label="Verified",
            ),
        ]
        with patch(
            "apps.planning.partner_oversight_service.build_items", return_value=items
        ) as build:
            partners = self._week(who=PARTNERS)["partners"]
        self.assertEqual(build.call_args.kwargs["fys"], ("2025", "2026", "2026"))
        self.assertEqual(
            [g["partner_name"] for g in partners["groups"]],
            ["Light Partners", "Calm Partners", "Quiet Partners"],
        )
        light = partners["groups"][0]
        self.assertEqual(
            [r["state_label"] for r in light["rows"]],
            [
                "Late since 14 Sep",
                "Not delivered",
                "In progress",
                "Evidence submitted",
                "Upcoming",
            ],
        )
        self.assertEqual(light["url"], "/partner-oversight/?partner=p1")
        self.assertEqual(
            partners["groups"][1]["rows"][0]["state_label"], "Not scheduled, due 14 Sep"
        )
        self.assertEqual(partners["groups"][2]["rows"][0]["state_label"], "Verified")
        self.assertEqual(
            (partners["done"], partners["not_delivered"], partners["late_before"]),
            (2, 1, 2),
        )

    def test_a_partner_read_that_fails_leaves_the_rest_of_the_week(self):
        with patch(
            "apps.planning.partner_oversight_service.build_items",
            side_effect=RuntimeError("down"),
        ):
            partners = self._week(who=PARTNERS)["partners"]
        self.assertTrue(partners["failed"])
        self.assertEqual(partners["groups"], [])

    # ── The page ─────────────────────────────────────────────────────────────
    def test_the_dashboard_opens_on_everyone_s_week(self):
        self._act(self.a1_sp, self.s1, monday_of(timezone.localdate()))
        self.client.force_login(self.pl)
        response = self.client.get("/dashboard")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["dashboard_view"], "week")
        self.assertContains(response, "data-pl-week-everyone")
        self.assertContains(response, "Hill School")
        self.assertContains(response, "Leadership Attention")
        self.assertNotContains(response, "Stranger School")

    def test_a_week_tab_swaps_the_week_panel_alone(self):
        self._act(
            self.a1_sp, self.s1, monday_of(timezone.localdate()) - timedelta(days=7)
        )
        self.client.force_login(self.pl)
        with patch(
            "apps.analytics.pl_dashboard_service.ProgramLeadDashboardService.get_dashboard"
        ) as dashboard:
            response = self.client.get(
                "/dashboard",
                {"view": "week", "who": self.a1_sp.id},
                HTTP_HX_REQUEST="true",
                HTTP_HX_TARGET="pl-week-panel",
            )
        self.assertFalse(dashboard.called)
        self.assertEqual(response.status_code, 200)
        html = response.content.decode()
        self.assertIn(f'data-pl-week-who="{self.a1_sp.id}"', html)
        self.assertNotIn("Leadership Attention", html)
        self.assertIn('data-pl-week-list="overdue"', html)
        for heading in ("School Visits", "Group Trainings", "Cluster Meetings"):
            self.assertIn(heading, html)
        # The visit table's own columns, in "What needs you now"'s order.
        for column in (
            "School ID",
            "School Name",
            "Activity",
            "Planned Date",
            "Executor",
            "Purpose of Visit",
            "Focus Intervention",
            "Cost",
            "Salesforce ID",
            "Evidence",
            "Status",
            "Actions",
        ):
            self.assertIn(f">{column}</th>", html)
        # Nothing entered or uploaded yet, and it says so.
        self.assertIn("Not in SF", html)
        self.assertIn("No Evidence Uploaded", html)
        self.assertIn('hx-post="/dashboard/pl-week-send/', html)
        self.assertIn("Send to Amos", html)

    def test_overdue_rows_are_red_and_bright_red_in_the_dark_themes(self):
        late = self._act(
            self.a1_sp, self.s1, monday_of(timezone.localdate()) - timedelta(days=7)
        )
        self.client.force_login(self.pl)
        html = self.client.get(
            "/dashboard", {"view": "week", "who": self.a1_sp.id, "list": OVERDUE}
        ).content.decode()
        self.assertRegex(html, rf'data-activity="{late.id}"[^>]*data-overdue')
        from pathlib import Path

        css = (
            Path(__file__).resolve().parents[2] / "static/css/components/pl-week.css"
        ).read_text()
        self.assertIn("--plwk-overdue: var(--edify-danger-text);", css)
        self.assertIn(":root.theme-dark .plwk {\n  --plwk-overdue: #ff5252;", css)
        self.assertIn(":root.theme-blue .plwk {\n  --plwk-overdue: #ff6b6b;", css)
        self.assertIn("tr[data-overdue] > :is(td, th)", css)
        # micro-ux.js marks cell content plain ink after load; the overdue
        # red must outrank consistency.css's rule for it, not only the
        # server-rendered markup.
        self.assertIn(
            "table.edify-plain-table.edify-plain-table.edify-plain-table\n"
            "  tr[data-overdue] .edify-table-plain-content",
            css,
        )

    def test_the_actions_column_is_pinned_so_it_is_never_scrolled_away(self):
        from pathlib import Path

        css = (
            Path(__file__).resolve().parents[2] / "static/css/components/pl-week.css"
        ).read_text()
        rule = css.split(
            ".plwk [data-pl-week-table] .edify-record-table :is(th, td):last-child {", 1
        )[1].split("}", 1)[0]
        self.assertIn("position: sticky;", rule)
        self.assertIn("inset-inline-end: 0;", rule)
        tables = (
            Path(__file__).resolve().parents[2]
            / "templates/partials/dashboards/pl/_week_tables.html"
        ).read_text()
        # Actions is the last column of every table.
        for head in tables.split("<thead")[1:]:
            last = head.split("</tr>", 1)[0].rstrip().rsplit("<th", 1)[1]
            self.assertIn(">Actions</th>", last)

    def test_verify_opens_the_lead_s_completion_review(self):
        activity = self._act(
            self.a1_sp,
            self.s1,
            monday_of(timezone.localdate()),
            status="submitted_to_pl",
            salesforce_activity_id="SV-123",
            evidence_status="uploaded",
        )
        self.client.force_login(self.pl)
        html = self.client.get(
            "/dashboard",
            {"view": "week", "who": self.a1_sp.id, "list": DUE_THIS_WEEK},
        ).content.decode()
        self.assertIn(f'hx-get="/pl/review-queue/{activity.id}/drawer"', html)
        self.assertIn(">Awaiting your verification<", html)
        drawer = self.client.get(f"/pl/review-queue/{activity.id}/drawer")
        self.assertEqual(drawer.status_code, 200)
        self.assertContains(drawer, "Verified")

    def test_send_to_reminds_the_officer_about_work_due_this_week(self):
        today = timezone.localdate()
        ahead = self._act(self.a1_sp, self.s1, today)
        self.client.force_login(self.pl)
        response = self.client.post(f"/dashboard/pl-week-send/{ahead.id}/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Sent to Amos")
        notice = Notification.objects.get(
            context_id=ahead.id, source_event_type="pl_activity_overdue_reminder"
        )
        self.assertIn("due", notice.title)
        self.assertIn("Salesforce ID", notice.body)
        html = self.client.get(
            "/dashboard", {"view": "week", "who": self.a1_sp.id, "list": DUE_THIS_WEEK}
        ).content.decode()
        self.assertIn("Sent to Amos", html)

        late = self._act(self.a1_sp, self.s1, monday_of(today) - timedelta(days=7))
        self.client.post(f"/dashboard/pl-week-send/{late.id}/")
        notice = Notification.objects.get(context_id=late.id)
        self.assertIn("Overdue", notice.title)

    def test_send_to_refuses_what_it_is_never_offered_on(self):
        today = timezone.localdate()
        refused = [
            # Completed by the officer: the lead verifies, not reminds.
            self._act(self.a1_sp, self.s1, today, status="submitted_to_pl"),
            self._act(self.a1_sp, self.s1, today, status="ia_verified"),
            self._act(self.a1_sp, self.s1, today, status="cancelled"),
            # Beyond this week.
            self._act(self.a1_sp, self.s1, monday_of(today) + timedelta(days=7)),
            # Another lead's officer.
            self._act(self.b1_sp, self.s3, today),
            # Partner-delivered work is Partner Monitoring's to chase.
            self._act(self.a1_sp, self.s1, today, delivery_type="partner"),
        ]
        self.client.force_login(self.pl)
        for activity in refused:
            with self.subTest(status=activity.status):
                response = self.client.post(f"/dashboard/pl-week-send/{activity.id}/")
                self.assertEqual(response.status_code, 403)
        self.assertFalse(Notification.objects.exists())
        self.client.force_login(self.a1)
        mine = self._act(self.a1_sp, self.s1, today)
        self.assertEqual(
            self.client.post(f"/dashboard/pl-week-send/{mine.id}/").status_code, 403
        )

    def test_the_past_due_reminder_is_unchanged(self):
        activity = self._act(
            self.a1_sp, self.s1, monday_of(timezone.localdate()) - timedelta(days=7)
        )
        self.client.force_login(self.pl)
        response = self.client.post(f"/dashboard/notify-past-due/{activity.id}/")
        self.assertEqual(response.status_code, 200)
        notice = Notification.objects.get(context_id=activity.id)
        self.assertEqual(notice.title, "Action Required: Overdue School Visit")
        self.assertIn("is past due", notice.body)
        self.assertIsNone(notice.resolved_at)

    def test_the_partners_tab_renders_its_empty_state(self):
        self.client.force_login(self.pl)
        response = self.client.get("/dashboard", {"view": "week", "who": PARTNERS})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "data-pl-week-partners")
        self.assertContains(response, "No partner work this week")

    def test_the_old_today_door_opens_the_me_tab(self):
        self.client.force_login(self.pl)
        response = self.client.get("/dashboard", {"view": "today"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["dashboard_view"], "week")
        self.assertEqual(response.context["week"]["who"], ME)
        self.assertContains(response, 'hx-vals=\'{"today_section": "own"}\'')

    def test_the_me_tab_s_workbench_leaves_out_the_team(self):
        today = timezone.localdate()
        self._act(self.a1_sp, self.s1, today)
        self.client.force_login(self.pl)
        whole = self.client.get("/today/panel")
        own = self.client.get("/today/panel", {"today_section": "own"})
        self.assertIsNotNone(whole.context["today"]["team_today"])
        self.assertContains(whole, "data-today-team")
        self.assertIsNone(own.context["today"]["team_today"])
        self.assertNotContains(own, "data-today-team")
        self.assertContains(own, "data-today-waiting")

    def test_the_team_s_week_drawer_reads_planned_dates_too(self):
        # Work carrying only a planned date was missing from this drawer when
        # it read the scheduled timestamp alone.
        from apps.core.fy import get_operational_fy

        fy = get_operational_fy()
        self._act(self.a1_sp, self.s1, monday_of(timezone.localdate()), fy=fy)
        self.client.force_login(self.pl)
        response = self.client.get(f"/dashboard/pl-drilldown?drill=week&fy={fy}")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Hill School")
