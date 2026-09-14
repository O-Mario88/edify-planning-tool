"""Today is where work is done (owner, 2026-09-14).

Pins: a queue row that is one decision carries its buttons and the decision
runs through the record's own service (so its refusals hold on Today too); a
decision needing a reason is refused without one and the refusal lands in the
row; snoozing hides a row until its day; Impact Assessment works its SSA
queue from its dashboard's Today view; an activity's next step opens its
drawer from the row.
"""

from __future__ import annotations

from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone

from apps.accounts.models import StaffProfile, StaffSupervisorAssignment, User
from apps.activities.models import Activity
from apps.command_center import today_actions
from apps.command_center.models import TodayActionRecord, TodoSnooze
from apps.core.rbac import EdifyRole
from apps.geography.models import District, Region
from apps.schools.models import School
from apps.ssa.models import SsaRecord, SsaScore


def _user(email, role, country="Uganda"):
    user = User.objects.create_user(
        email=email,
        name=email.split("@")[0].title(),
        roles=[role],
        active_role=role,
        password="x",
        is_active=True,
    )
    staff = StaffProfile.objects.create(user=user, title=role, country=country)
    return user, staff


def _row(todo_id, **extra):
    return {
        "id": todo_id,
        "title": extra.pop("title", "Item"),
        "description": "",
        "category": "Test",
        "priority": extra.pop("priority", "high"),
        "status_key": "waiting_me",
        "actionable": True,
        "action_label": extra.pop("action_label", "Open"),
        "action_url": extra.pop("action_url", "/todos"),
        **extra,
    }


class AdapterMatchTests(TestCase):
    def test_ids_name_their_decision_and_links_tell_same_shapes_apart(self):
        cases = {
            "plrev-abc": "completion_review",
            "wfr-appr-abc": "weekly_fund_approval",
            "wfrreceipt-abc": "weekly_receipt",
            "frreceipt-abc": "monthly_receipt",
            "wfr-cmtwy4af500b361kfffvf": "weekly_fund_request",
            "leave-abc": "leave_approval",
            "visitreq-abc": "visit_request",
            "sch-abc-contact": "school_contact",
            "sch-abc-ssa": "ssa_visit",
            "ssa-next-abc": "ssa_verification",
        }
        for todo_id, kind in cases.items():
            with self.subTest(todo_id=todo_id):
                adapter, record_id = today_actions.adapter_for(todo_id, _row(todo_id))
                self.assertEqual(adapter.kind, kind)
                self.assertTrue(record_id)
        partner = _row(
            "ia-cmtlfliu200a20eecdhrq",
            action_url="/ia/partner-evidence/cmtlfliu200a20eecdhrq/",
        )
        staff = _row(
            "ia-cmtlfliu200a20eecdhrq",
            action_url="/ia/verification/cmtlfliu200a20eecdhrq/",
        )
        self.assertEqual(
            today_actions.adapter_for(partner["id"], partner)[0].kind,
            "partner_evidence",
        )
        # Staff work is verified against its checklist on its own page.
        self.assertIsNone(today_actions.adapter_for(staff["id"], staff)[0])

    def test_an_activity_step_link_opens_its_drawer_from_the_row(self):
        row = _row(
            "act-cmtlflhvf008ntgecdhgp",
            action_label="Upload",
            action_url="/activities/cmtlflhvf008ntgecdhgp/evidence",
        )
        decorated = today_actions.decorate([row], None)[0]["today"]
        self.assertEqual(decorated["kind"], "record_form")
        self.assertEqual(
            decorated["operations"][0]["drawer_url"],
            "/activities/cmtlflhvf008ntgecdhgp/evidence",
        )
        page = _row("act-x", action_url="/my-plan/x")
        self.assertEqual(
            today_actions.decorate([page], None)[0]["today"]["operations"], []
        )


class CompletionDecisionTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        region = Region.objects.create(name="TA Region")
        district = District.objects.create(name="TA District", region=region)
        cls.school = School.objects.create(
            name="TA Primary", school_id="TA-1", region=region, district=district
        )
        cls.pl, cls.pl_sp = _user("ta-pl@t.org", EdifyRole.COUNTRY_PROGRAM_LEAD.value)
        cls.cceo, cls.cceo_sp = _user("ta-cceo@t.org", EdifyRole.CCEO.value)
        StaffSupervisorAssignment.objects.create(
            supervisee=cls.cceo_sp, supervisor=cls.pl_sp
        )
        cls.other_pl, _ = _user("ta-pl2@t.org", EdifyRole.COUNTRY_PROGRAM_LEAD.value)

    def setUp(self):
        self.activity = Activity.objects.create(
            school_id=self.school.id,
            activity_type="school_visit",
            status="submitted_to_pl",
            fy="2026",
            quarter="Q4",
            responsible_staff_id=self.cceo_sp.id,
            planned_date=timezone.now(),
        )
        self.todo = f"plrev-{self.activity.id}"

    def _act(self, user, op, **extra):
        self.client.force_login(user)
        return self.client.post(
            "/today/act",
            {"todo": self.todo, "op": op, "title": "Review Completion", **extra},
            HTTP_HX_REQUEST="true",
        )

    def test_the_lead_confirms_from_the_row(self):
        response = self._act(self.pl, "confirm")
        self.assertContains(response, "data-today-item-done")
        self.assertContains(response, "sent to Impact Assessment")
        self.activity.refresh_from_db()
        self.assertEqual(self.activity.status, "awaiting_ia_verification")
        record = TodayActionRecord.objects.get(user_id=str(self.pl.id))
        self.assertEqual(
            (record.kind, record.operation), ("completion_review", "confirm")
        )
        self.assertEqual(today_actions.cleared_today(self.pl), 1)

    def test_a_return_needs_a_reason_and_the_refusal_lands_in_the_row(self):
        response = self._act(self.pl, "return")
        self.assertIn("data-today-error", response["HX-Retarget"])
        self.assertContains(response, "is required")
        self.activity.refresh_from_db()
        self.assertEqual(self.activity.status, "submitted_to_pl")

        response = self._act(self.pl, "return", reason="Photos are unreadable")
        self.assertContains(response, "data-today-item-done")
        self.activity.refresh_from_db()
        self.assertEqual(self.activity.status, "returned_by_pl")
        self.assertEqual(self.activity.pl_review_note, "Photos are unreadable")

    def test_the_service_still_refuses_a_lead_outside_the_team(self):
        response = self._act(self.other_pl, "confirm")
        self.assertIn("HX-Retarget", response)
        self.activity.refresh_from_db()
        self.assertEqual(self.activity.status, "submitted_to_pl")
        self.assertFalse(TodayActionRecord.objects.exists())

    def test_an_unknown_operation_or_item_is_refused(self):
        self.assertIn("HX-Retarget", self._act(self.pl, "delete"))
        self.todo = "coaching-anything"
        self.assertIn("HX-Retarget", self._act(self.pl, "log"))


class SnoozeTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.pl, _ = _user("tz-pl@t.org", EdifyRole.COUNTRY_PROGRAM_LEAD.value)

    def test_a_snoozed_row_leaves_today_until_its_day_and_undo_brings_it_back(self):
        from apps.frontend.views.today_views import _split_todos

        rows = [_row("pl-analytics-ssa", title="Follow up SSA")]
        with patch(
            "apps.command_center.todo_service.get_cached_todos",
            return_value={"todos": rows, "total": 1},
        ):
            self.assertEqual(len(_split_todos(self.pl)[0]), 1)
            self.client.force_login(self.pl)
            response = self.client.post(
                "/today/snooze",
                {
                    "todo": "pl-analytics-ssa",
                    "choice": "tomorrow",
                    "title": "Follow up",
                },
                HTTP_HX_REQUEST="true",
            )
            self.assertContains(response, "snoozed until")
            self.assertContains(response, "Undo")
            snooze = TodoSnooze.objects.get(user_id=str(self.pl.id))
            self.assertGreater(snooze.until, timezone.localdate())
            self.assertEqual(_split_todos(self.pl)[0], [])

            response = self.client.post(
                "/today/unsnooze",
                {"todo": "pl-analytics-ssa"},
                HTTP_HX_REQUEST="true",
            )
            self.assertEqual(response["HX-Retarget"], "[data-dashboard-today]")
            self.assertEqual(len(_split_todos(self.pl)[0]), 1)

    def test_a_snooze_choice_must_be_one_offered(self):
        self.client.force_login(self.pl)
        response = self.client.post(
            "/today/snooze",
            {"todo": "pl-analytics-ssa", "choice": "forever"},
            HTTP_HX_REQUEST="true",
        )
        self.assertIn("HX-Retarget", response)
        self.assertFalse(TodoSnooze.objects.exists())


class ImpactAssessmentTodayTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        region = Region.objects.create(name="TI Central", country="Uganda")
        district = District.objects.create(name="TI Wakiso", region=region)
        cls.school = School.objects.create(
            school_id="TI-UG-1", name="TI Kampala", region=region, district=district
        )
        cls.ia, _ = _user("ti-ia@t.org", EdifyRole.IMPACT_ASSESSMENT.value)
        cls.ia2, _ = _user("ti-ia2@t.org", EdifyRole.IMPACT_ASSESSMENT.value)

    def setUp(self):
        self.record = SsaRecord.objects.create(
            school=self.school,
            date_of_ssa=timezone.make_aware(timezone.datetime(2026, 5, 1, 9)),
            fy="2026",
            quarter="Q3",
            average_score=5.5,
            collector_type="staff",
            verification_status="pending",
            uploaded_by=self.ia2.id,
            collected_by_user_id=self.ia2.id,
        )
        for intervention, score in (("leadership", 3.0), ("enrolment", 8.0)):
            SsaScore.objects.create(
                ssa_record=self.record, intervention=intervention, score=score
            )

    def test_the_dashboard_has_a_today_view_and_the_old_door_leads_there(self):
        self.client.force_login(self.ia)
        page = self.client.get("/ia/dashboard/?view=today")
        self.assertContains(page, 'id="dashboard-tab-today"')
        self.assertContains(page, 'hx-get="/today/panel"')
        self.assertRedirects(
            self.client.get("/today"),
            "/ia/dashboard/?view=today",
            fetch_redirect_response=False,
        )

    def test_a_verifier_confirms_the_next_ssa_from_today(self):
        self.client.force_login(self.ia)
        panel = self.client.get("/today/panel")
        self.assertEqual(panel.context["today"]["mode"], "desk")
        self.assertContains(panel, "Verify SSA")
        self.assertContains(panel, "Leadership 3.0")
        self.assertNotContains(panel, "Your next activity")
        response = self.client.post(
            "/today/act",
            {
                "todo": f"ssa-next-{self.record.id}",
                "op": "confirm",
                "title": "Verify SSA",
            },
            HTTP_HX_REQUEST="true",
        )
        self.assertContains(response, "now informs planning")
        self.record.refresh_from_db()
        self.assertEqual(self.record.verification_status, "confirmed")

    def test_the_collector_is_not_offered_their_own_ssa(self):
        self.assertIsNone(today_actions.next_ssa_row(self.ia2))
        self.client.force_login(self.ia2)
        response = self.client.post(
            "/today/act",
            {"todo": f"ssa-next-{self.record.id}", "op": "confirm"},
            HTTP_HX_REQUEST="true",
        )
        self.assertIn("HX-Retarget", response)
        self.record.refresh_from_db()
        self.assertEqual(self.record.verification_status, "pending")


class ReceiptAttestationTests(TestCase):
    def test_a_receipt_is_not_confirmed_without_the_attestation(self):
        user, _ = _user("tr-cceo@t.org", EdifyRole.CCEO.value)
        with self.assertRaisesMessage(Exception, "Tick"):
            today_actions.perform(user, "wfrreceipt-abc", "confirm")
