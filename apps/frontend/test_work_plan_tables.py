from types import SimpleNamespace
from django.test import SimpleTestCase
from django.template.loader import render_to_string
from apps.frontend.work_plan_tables import (
    DETAIL_PAGE_PARAM,
    detail_fields,
    work_plan_action,
)


class WorkPlanTablesTests(SimpleTestCase):
    def activity(self, **kwargs):
        values = dict(
            id="activity-1",
            activity_type="school_visit",
            school_id="pk-1",
            school=SimpleNamespace(name="Grace", school_id="SCH-42"),
            cluster_id=None,
            status="scheduled",
            reschedule_count=0,
            schools_invited=3,
            cluster_school_count_snapshot=9,
            teachers_per_school=2,
            leaders_per_school=1,
            other_per_school=0,
            delivery_type="staff",
            venue="Hall",
        )
        return SimpleNamespace(**(values | kwargs))

    def test_explicit_non_school_and_cluster_classification(self):
        self.assertEqual(
            detail_fields(self.activity(), "non_school", "Q4")["detail_group"],
            "non_school",
        )
        self.assertEqual(
            detail_fields(
                self.activity(activity_type="cluster_training"), "school", "Q4"
            )["detail_group"],
            "cluster",
        )
        self.assertEqual(
            detail_fields(self.activity(), "school", "Q4")["school_code"], "SCH-42"
        )

    def test_invited_count_not_cluster_membership_or_attendance(self):
        row = detail_fields(self.activity(), "school", "Q4")
        self.assertEqual(
            (
                row["schools_invited"],
                row["teachers_invited"],
                row["leaders_invited"],
                row["others_invited"],
            ),
            (3, 6, 3, 0),
        )
        row = detail_fields(
            self.activity(schools_invited=None, teachers_per_school=None),
            "school",
            "Q4",
        )
        self.assertEqual(row["schools_invited"], 9)
        self.assertIsNone(row["teachers_invited"])

    def test_status_is_scheduled_or_complete(self):
        """Owner, 2026-10-05: "Status (Scheduled or Complete)". Work that was
        moved is still scheduled; work called off says so; a plan with no
        date yet is not scheduled."""
        for status, label in [
            ("cancelled", "Cancelled"),
            ("closed", "Complete"),
            ("completed", "Complete"),
            ("scheduled", "Scheduled"),
            ("rescheduled", "Scheduled"),
        ]:
            self.assertEqual(
                detail_fields(
                    self.activity(status=status, reschedule_count=1), "school", "Q4"
                )["delivery_status"],
                label,
            )
        undated = self.activity(
            status="planned", planned_date=None, scheduled_date=None
        )
        self.assertEqual(
            detail_fields(undated, "school", "Q4")["delivery_status"], "Planned"
        )

    def test_each_column_reads_the_owners_words(self):
        """Owner, 2026-10-05: Activity is a Training or a Visit or what else
        was planned; Activity Purpose is In-school Training, a follow up,
        Group Training, Cluster Meeting, a camp or a conference; Delivery
        Mode is In-school Training, School Visit, Group Training or Cluster
        Meeting."""
        cases = [
            # activity, group -> (Activity, Activity Purpose, Delivery Mode)
            (
                self.activity(purpose_type="training_follow_up"),
                "school",
                ("Visit", "Training Follow Up", "School Visit"),
            ),
            (
                self.activity(purpose_type="in_school_training_delivery_visit"),
                "school",
                ("Visit", "In-school Training", "School Visit"),
            ),
            (
                self.activity(activity_type="in_school_training"),
                "school",
                ("Training", "In-school Training", "In-school Training"),
            ),
            (
                self.activity(
                    activity_type="cluster_training", school_id=None, cluster_id="c1"
                ),
                "school",
                ("Training", "Group Training", "Group Training"),
            ),
            (
                self.activity(
                    activity_type="cluster_meeting", school_id=None, cluster_id="c1"
                ),
                "school",
                ("Meeting", "Cluster Meeting", "Cluster Meeting"),
            ),
            (
                self.activity(
                    activity_type="programme_event",
                    school_id=None,
                    programme_activity_type="youth_camp",
                    activity_name_snapshot="Student Leadership Camp",
                    programme_delivery_mode="group",
                ),
                "non_school",
                ("Youth Camp", "Student Leadership Camp", "Group"),
            ),
        ]
        for activity, group, expected in cases:
            if activity.cluster_id:
                activity.cluster = SimpleNamespace(name="North", district=None)
            row = detail_fields(activity, group, "Q4")
            with self.subTest(expected=expected):
                self.assertEqual(
                    (
                        row["activity_word"],
                        row["activity_purpose"],
                        row["delivery_mode"],
                    ),
                    expected,
                )

    def test_place_columns_come_from_the_school_or_its_cluster(self):
        school = SimpleNamespace(
            name="Grace", school_id="SCH-42", district=SimpleNamespace(name="Dokolo")
        )
        row = detail_fields(
            self.activity(school=school, source_score=2),
            "school",
            "Q4",
            school_cluster_name="Dokolo East",
        )
        self.assertEqual(
            (row["school_code"], row["school_name"], row["district_name"]),
            ("SCH-42", "Grace", "Dokolo"),
        )
        # The cluster the school sits in, when the work names none itself.
        self.assertEqual(row["cluster_name"], "Dokolo East")
        self.assertEqual(row["previous_ssa_score"], "2.0")

        cluster = SimpleNamespace(name="North", district=SimpleNamespace(name="Lira"))
        row = detail_fields(
            self.activity(
                activity_type="cluster_meeting",
                school_id=None,
                cluster_id="c1",
                cluster=cluster,
            ),
            "school",
            "Q4",
        )
        self.assertEqual(
            (row["school_code"], row["school_name"], row["cluster_name"]),
            ("", "", "North"),
        )
        self.assertEqual(row["district_name"], "Lira")
        self.assertEqual(row["previous_ssa_score"], "—")

    def test_owner_edits_existing_activity_supervisor_composes_and_readonly_does_not_act(
        self,
    ):
        activity = self.activity()
        action = work_plan_action(activity, owned=True, enabled=True)
        self.assertEqual(action["url"], "/my-plan/activity-1/reschedule-drawer")
        # Their own scheduled work: Complete, Reschedule and Cancel.
        self.assertEqual(action["text"], "Reschedule")
        self.assertTrue(action["own"])
        self.assertTrue(action["complete"])
        undated = work_plan_action(
            self.activity(status="planned", planned_date=None, scheduled_date=None),
            owned=True,
            enabled=True,
        )
        self.assertEqual(undated["text"], "Schedule")
        self.assertFalse(undated["complete"])
        action = work_plan_action(
            activity,
            owned=False,
            enabled=True,
            recipient="person-1",
            recipient_name="Jane",
        )
        self.assertEqual(action["text"], "Send to Jane")
        self.assertIn("context_id=activity-1", action["url"])
        self.assertIn("to=person-1", action["url"])
        self.assertNotIn("own", action)
        # The Country Director's message goes to the Program Lead.
        to_lead = work_plan_action(
            activity,
            owned=False,
            enabled=True,
            recipient="lead-1",
            recipient_name="Denis",
            recipient_label="PL",
        )
        self.assertEqual(to_lead["text"], "Send to PL")
        self.assertIn("to=lead-1", to_lead["url"])
        self.assertIn("Denis", to_lead["description"])
        self.assertIsNone(
            work_plan_action(activity, owned=False, enabled=False, recipient="person-1")
        )
        self.assertEqual(
            work_plan_action(
                self.activity(status="completed"), owned=True, enabled=True
            )["text"],
            "View",
        )

    def test_one_table_always_renders_its_fifteen_columns(self):
        from html.parser import HTMLParser

        class TableHeaders(HTMLParser):
            def __init__(self):
                super().__init__()
                self.counts = []

            def handle_starttag(self, tag, attrs):
                if tag == "table":
                    self.counts.append(0)
                if tag == "th" and ("scope", "col") in attrs:
                    self.counts[-1] += 1

        html = render_to_string(
            "partials/work_plan/detail_tables.html",
            {
                "detail_rows": [],
                "detail_page_param": DETAIL_PAGE_PARAM,
                "period_label": "Q4",
            },
        )
        parser = TableHeaders()
        parser.feed(html)
        self.assertEqual(parser.counts, [15])
        self.assertEqual(html.count("No activities planned"), 1)
        for heading in (
            "Activity Date",
            "Activity",
            "School ID",
            "School Name",
            "District",
            "Cluster Name",
            "Activity Purpose",
            "SSA Intervention",
            "Previous SSA Score",
            "Delivery Mode",
            "Person Responsible",
            "Cost",
            "Planned Period",
            "Status",
            "Action",
        ):
            self.assertIn(f'<th scope="col">{heading}</th>', html)

    def test_message_recipient_prefill_respects_allowed_recipients(self):
        from contextlib import ExitStack
        from unittest.mock import patch
        from django.test import RequestFactory
        from apps.frontend.views.message_views import _compose_context

        with ExitStack() as stack:
            allowed = [{"id": "allowed", "name": "Jane", "role": "CCEO"}]
            for name, result in [
                ("recipients", allowed),
                ("categories_for_role", []),
                ("drafts_for_user", []),
                ("search_context_records", []),
            ]:
                stack.enter_context(
                    patch(
                        "apps.frontend.views.message_views.services." + name,
                        return_value=result,
                    )
                )
            for recipient, expected in [("allowed", allowed), ("outside-scope", [])]:
                request = RequestFactory().get("/messages/new", {"to": recipient})
                request.user = SimpleNamespace(id="viewer")
                self.assertEqual(_compose_context(request)["pre_to"], expected)
