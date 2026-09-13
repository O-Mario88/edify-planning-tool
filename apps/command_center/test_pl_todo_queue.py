"""The Programme Lead's To-Do queue (Program Lead alignment, 2026-09-13).

A lead's queue is the lead's work: the team's handoffs they decide, and their
own portfolio's chores. It is not every officer's slot, contact and loan visit
re-listed on the lead's desk as work the lead cannot plan into (owner rule:
nobody plans into another's portfolio). Rows the lead decides carry the
responsibility they belong to, so the queue reads the way the role does.
"""

from __future__ import annotations

from datetime import date, timedelta

from django.db import connection
from django.test import SimpleTestCase, TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from apps.accounts.models import (
    StaffProfile,
    StaffSchoolAssignment,
    StaffSupervisorAssignment,
    User,
)
from apps.activities.models import Activity, ActivityScheduleCostLine
from apps.command_center import todo_service
from apps.command_center.todo_service import (
    get_todos,
    is_leadership_handoff,
    pl_responsibility_for,
)
from apps.core.fy import get_operational_fy
from apps.core_schools.models import CoreActivitySlot, CorePlan
from apps.fund_requests.models import (
    AdvanceRequest,
    WeeklyFundRequest,
    WeeklyFundRequestLine,
)
from apps.geography.models import District, Region
from apps.schools.models import School

LOCMEM = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "pl-todo-queue",
    }
}
FY = "2026"


def _staff(email, name, role):
    user = User.objects.create_user(
        email=email,
        name=name,
        roles=[role],
        active_role=role,
        password="x",
        is_active=True,
    )
    return user, StaffProfile.objects.create(user=user, title=role)


def _rows(user, prefix):
    return [t for t in get_todos(user)["todos"] if t["id"].startswith(prefix)]


@override_settings(CACHES=LOCMEM)
class ProgramLeadTodoQueueTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.region = Region.objects.create(name="PLQ Region")
        cls.district = District.objects.create(name="PLQ District", region=cls.region)
        cls.pl, cls.pl_sp = _staff("plq-lead@t.org", "Lead A", "Program Lead")
        cls.cceo, cls.cceo_sp = _staff("plq-a1@t.org", "Officer A1", "CCEO")
        StaffSupervisorAssignment.objects.create(
            supervisor=cls.pl_sp, supervisee=cls.cceo_sp
        )
        cls.pl_b, cls.pl_b_sp = _staff("plq-leadb@t.org", "Lead B", "Program Lead")
        cls.cceo_b, cls.cceo_b_sp = _staff("plq-b1@t.org", "Officer B1", "CCEO")
        StaffSupervisorAssignment.objects.create(
            supervisor=cls.pl_b_sp, supervisee=cls.cceo_b_sp
        )
        cls.team_school = cls._school("PLQ-TEAM", cls.cceo_sp)
        cls.own_school = cls._school("PLQ-OWN", cls.pl_sp)
        cls.other_school = cls._school("PLQ-OTHER", cls.cceo_b_sp)

    @classmethod
    def _school(cls, code, staff, **extra):
        school = School.objects.create(
            school_id=code,
            name=f"School {code}",
            region=cls.region,
            district=cls.district,
            **extra,
        )
        StaffSchoolAssignment.objects.create(staff=staff, school_id=school.id)
        return school

    def _week(self, owner, offset, status="submitted_to_pl"):
        start = date(2026, 7, 6) + timedelta(days=7 * offset)
        return WeeklyFundRequest.objects.create(
            fy=FY,
            week_start_date=start,
            week_end_date=start + timedelta(days=6),
            responsible_user=owner.id,
            total_amount=50_000,
            status=status,
        )

    def _advance(
        self, owner_user, owner_sp, school, status="accountability_pl_pending"
    ):
        activity = Activity.objects.create(
            school=school,
            activity_type="school_visit",
            delivery_type="staff",
            status="completed",
            responsible_staff_id=owner_sp.id,
            fy=FY,
            quarter="Q3",
            planned_date=date(2026, 7, 8),
        )
        line = ActivityScheduleCostLine.objects.create(
            activity=activity,
            cost_setting_key="transport",
            label="Transport",
            unit_cost=20_000,
            amount=20_000,
        )
        advance, _ = AdvanceRequest.objects.update_or_create(
            activity=activity,
            budget_line=line,
            defaults={
                "responsible_user_id": owner_user.id,
                "fy": FY,
                "quarter": "Q3",
                "amount": 20_000,
                "status": status,
                "accountability_submitted_at": timezone.now(),
            },
        )
        return advance, line

    # ── Fund approvals ───────────────────────────────────────────────────────
    def test_one_fund_approval_row_per_supervised_request(self):
        first = self._week(self.cceo, 0)
        second = self._week(self.cceo, 1)
        self._week(self.cceo_b, 0)

        rows = _rows(self.pl, "wfr-appr-")
        self.assertEqual(
            {r["id"] for r in rows}, {f"wfr-appr-{first.id}", f"wfr-appr-{second.id}"}
        )
        for row in rows:
            self.assertEqual(row["action_url"], "/fund-approvals")
            self.assertTrue(row["description"].startswith("Officer A1's week of"))
            self.assertEqual(row["category"], "Finance & Budget")
        # The per-officer "Review … Fund Plan" duplicate is gone.
        self.assertEqual(_rows(self.pl, "plfund-"), [])
        self.assertFalse(hasattr(todo_service, "_pl_fund_todos"))

    def test_the_country_director_keeps_the_request_s_own_page(self):
        cd, _cd_sp = _staff("plq-cd@t.org", "Country Director", "CountryDirector")
        own = self._week(self.pl, 3, status="submitted_to_cd")
        row = next(r for r in _rows(cd, "wfr-appr-") if r["id"].endswith(own.id))
        self.assertEqual(row["action_url"], f"/fund-requests/weekly/{own.id}")

    def test_an_accountability_row_opens_its_own_weekly_request(self):
        """The row used to link to `w.id` — whichever request the approval
        loop finished on — so the lead landed on another officer's week."""
        unrelated = self._week(self.cceo, 5)
        advance, line = self._advance(self.cceo, self.cceo_sp, self.team_school)
        drawn_on = self._week(self.cceo, 2, status="confirmed_for_advance")
        WeeklyFundRequestLine.objects.create(
            weekly_fund_request=drawn_on,
            activity_budget_line=line,
            line_item_type="transport",
            description="Transport",
            unit_cost=20_000,
            total_cost=20_000,
        )
        orphan, _line = self._advance(self.cceo, self.cceo_sp, self.team_school)

        rows = {r["id"]: r for r in _rows(self.pl, "adv-plakt-")}
        self.assertEqual(
            rows[f"adv-plakt-{advance.id}"]["action_url"],
            f"/fund-requests/weekly/{drawn_on.id}",
        )
        self.assertNotEqual(
            rows[f"adv-plakt-{advance.id}"]["action_url"],
            f"/fund-requests/weekly/{unrelated.id}",
        )
        self.assertEqual(
            rows[f"adv-plakt-{orphan.id}"]["action_url"], "/fund-approvals"
        )

    def test_an_accountability_row_survives_a_lead_with_no_requests_to_approve(self):
        """With nothing to approve the stale `w` was unbound: a NameError took
        the whole finance source out of the lead's queue."""
        advance, _line = self._advance(self.cceo_b, self.cceo_b_sp, self.other_school)
        ids = {r["id"] for r in _rows(self.pl_b, "adv-plakt-")}
        self.assertEqual(ids, {f"adv-plakt-{advance.id}"})
        self.assertEqual(_rows(self.pl, "adv-plakt-"), [])

    # ── The lead's own portfolio, not the team's ─────────────────────────────
    def test_school_data_quality_rows_are_the_lead_s_own_schools_only(self):
        pl_ids = {r["id"] for r in _rows(self.pl, "sch-")}
        self.assertIn(f"sch-{self.own_school.id}-contact", pl_ids)
        self.assertNotIn(f"sch-{self.team_school.id}-contact", pl_ids)
        cceo_ids = {r["id"] for r in _rows(self.cceo, "sch-")}
        self.assertIn(f"sch-{self.team_school.id}-contact", cceo_ids)

    def test_a_lead_with_no_schools_of_their_own_gets_no_data_quality_rows(self):
        self.assertEqual(_rows(self.pl_b, "sch-"), [])

    def _core_plan(self, school, owner_sp):
        school.school_type = "core"
        school.save(update_fields=["school_type"])
        plan = CorePlan.objects.create(
            id=f"cplan-{school.school_id}",
            school_id=school.school_id,
            fy=get_operational_fy(),
        )
        for kind, sequence in (("assessment", 1), ("visit", 1), ("training", 1)):
            CoreActivitySlot.objects.create(
                id=f"cslot-{school.school_id}-{kind}",
                core_plan=plan,
                school_id=school.school_id,
                intervention="leadership",
                activity_type=kind,
                sequence_number=sequence,
                status="Planned",
            )
        return plan

    def test_core_school_rows_are_own_slots_plus_one_follow_up_per_officer(self):
        self._core_plan(self.own_school, self.pl_sp)
        self._core_plan(self.team_school, self.cceo_sp)
        second = self._school("PLQ-TEAM-2", self.cceo_sp)
        self._core_plan(second, self.cceo_sp)

        slot_rows = _rows(self.pl, "core-slot-")
        self.assertTrue(slot_rows)
        self.assertTrue(
            all(self.own_school.school_id in r["id"] for r in slot_rows), slot_rows
        )
        team_rows = _rows(self.pl, "core-team-")
        self.assertEqual([r["id"] for r in team_rows], [f"core-team-{self.cceo_sp.id}"])
        self.assertEqual(
            team_rows[0]["title"], "Follow up Officer A1's core school plan"
        )
        self.assertIn("across 2 core schools", team_rows[0]["description"])
        self.assertEqual(team_rows[0]["category"], "Programme Implementation")
        # The officer still carries their own slots.
        officer_slots = {r["id"] for r in _rows(self.cceo, "core-slot-")}
        self.assertIn(
            f"core-slot-cslot-{self.team_school.school_id}-visit", officer_slots
        )
        self.assertEqual(_rows(self.cceo, "core-team-"), [])

    def test_loan_use_verification_rows_are_the_lead_s_own_schools_only(self):
        from apps.business_transformation.models import (
            LoanPurpose,
            LoanVerificationRequirement,
            MfiLoan,
            MfiOrganization,
            TransformationCase,
        )

        mfi = MfiOrganization.objects.create(code="PLQ-MFI", name="PLQ MFI")
        purpose = LoanPurpose.objects.create(code="PLQ-PURPOSE", label="Classrooms")

        def requirement(school, reference):
            case = TransformationCase.objects.create(
                school=school, status="active", opened_fy=FY
            )
            loan = MfiLoan.objects.create(
                mfi=mfi,
                school=school,
                case=case,
                purpose=purpose,
                external_loan_reference=reference,
            )
            req, _ = LoanVerificationRequirement.objects.get_or_create(
                loan=loan,
                defaults={"due_date": timezone.localdate() + timedelta(days=10)},
            )
            return req

        own = requirement(self.own_school, "PLQ-OWN")
        team = requirement(self.team_school, "PLQ-TEAM")

        pl_rows = {r["id"]: r for r in _rows(self.pl, "bt-field-verification-")}
        self.assertEqual(set(pl_rows), {f"bt-field-verification-{own.id}"})
        self.assertTrue(
            pl_rows[f"bt-field-verification-{own.id}"]["action_url"].startswith(
                f"/schools/{self.own_school.school_id}"
            )
        )
        for row in get_todos(self.pl)["todos"]:
            self.assertNotIn("/business-transformation", row["action_url"])
        cceo_ids = {r["id"] for r in _rows(self.cceo, "bt-field-verification-")}
        self.assertIn(f"bt-field-verification-{team.id}", cceo_ids)

    # ── Partner invoices ─────────────────────────────────────────────────────
    def _invoice(self, monitor_sp, school, code):
        from apps.fund_requests.finance_models import PartnerInvoice, PartnerInvoiceItem

        activity = Activity.objects.create(
            school=school,
            activity_type="school_visit",
            delivery_type="partner",
            status="completed",
            responsible_staff_id=None,
            monitored_by_staff_id=monitor_sp.id,
            fy=FY,
            quarter="Q3",
            planned_date=date(2026, 7, 8),
        )
        invoice = PartnerInvoice.objects.create(
            partner_id=f"partner-{code}",
            invoice_type="advance",
            period_kind="month",
            period_start=date(2026, 7, 1),
            period_end=date(2026, 7, 31),
            system_total=40_000,
            entered_total=40_000,
            payable_amount=20_000,
            stored_name=f"{code}.pdf",
            original_name=f"{code}.pdf",
            submitted_by="partner-user",
        )
        PartnerInvoiceItem.objects.create(
            invoice=invoice,
            activity=activity,
            instalment="advance",
            planned_amount=40_000,
            payable_amount=20_000,
            category="School Visits",
        )
        return invoice

    def test_partner_invoice_rows_are_the_lead_s_team_only_in_one_read(self):
        """The lead's invoices are asked for in the query — a partner's work
        monitored by one of the lead's officers — not by three reads per
        invoice after a country-wide cut to twenty."""
        mine = self._invoice(self.cceo_sp, self.team_school, "PLQ-INV-A")
        theirs = self._invoice(self.cceo_b_sp, self.other_school, "PLQ-INV-B")

        rows = {r["id"]: r for r in _rows(self.pl, "pinv-")}
        self.assertEqual(set(rows), {f"pinv-{mine.id}"})
        self.assertEqual(rows[f"pinv-{mine.id}"]["action_url"], "/fund-approvals")
        self.assertEqual(rows[f"pinv-{mine.id}"]["category"], "Finance & Budget")
        self.assertEqual(
            {r["id"] for r in _rows(self.pl_b, "pinv-")}, {f"pinv-{theirs.id}"}
        )

        with CaptureQueriesContext(connection) as captured:
            todo_service._partner_invoice_todos(self.pl, "Program Lead")
        self.assertLessEqual(len(captured.captured_queries), 3)


class ResponsibilityCategoryTest(SimpleTestCase):
    def test_lead_rows_map_to_the_five_responsibilities(self):
        cases = {
            "wfr-appr-1": "Finance & Budget",
            "plrev-a": "Programme Implementation",
            "core-team-s": "Programme Implementation",
            "leave-9": "Team Leadership",
            "debrief-escalated-3": "Team Leadership",
            "team-risk-u": "Performance & Coaching",
            "pd-review-2": "Performance & Coaching",
            "cdflag-7": "Collaboration",
            "visitreq-4": "Collaboration",
            "pinv-5": "Finance & Budget",
        }
        for row_id, category in cases.items():
            with self.subTest(row_id=row_id):
                self.assertEqual(pl_responsibility_for({"id": row_id}), category)
        self.assertIsNone(pl_responsibility_for({"id": "act-1"}))
        self.assertIsNone(pl_responsibility_for({"id": "core-slot-1"}))

    def test_handoffs_are_told_apart_from_the_lead_s_own_field_chores(self):
        self.assertTrue(is_leadership_handoff({"id": "wfr-appr-1"}))
        self.assertTrue(is_leadership_handoff({"id": "coaching-hold-1"}))
        self.assertTrue(
            is_leadership_handoff({"id": "x-1", "category": "Collaboration"})
        )
        for chore in ("act-1", "sch-1-contact", "core-slot-1", "wfr-9", "bt-field-1"):
            with self.subTest(chore=chore):
                self.assertFalse(is_leadership_handoff({"id": chore}))


@override_settings(CACHES=LOCMEM)
class ProgramLeadTodoQueryBudgetTest(TestCase):
    """What a Programme Lead's queue costs, and that the team does not
    multiply it. A ceiling, never a target."""

    #: Measured at 155 on 2026-09-13 against this fixture with one officer.
    CEILING = 190
    #: Queries four more officers may add in total.
    GROWTH = 12

    @classmethod
    def setUpTestData(cls):
        cls.region = Region.objects.create(name="PLQB Region")
        cls.district = District.objects.create(name="PLQB District", region=cls.region)
        cls.pl, cls.pl_sp = _staff("plqb-lead@t.org", "Budget Lead", "Program Lead")
        cls.serial = 0
        cls._officer()

    @classmethod
    def _officer(cls):
        cls.serial += 1
        n = cls.serial
        user, sp = _staff(f"plqb-{n}@t.org", f"Budget Officer {n}", "CCEO")
        StaffSupervisorAssignment.objects.create(supervisor=cls.pl_sp, supervisee=sp)
        school = School.objects.create(
            school_id=f"PLQB-{n}",
            name=f"Budget School {n}",
            region=cls.region,
            district=cls.district,
            school_type="core",
        )
        StaffSchoolAssignment.objects.create(staff=sp, school_id=school.id)
        plan = CorePlan.objects.create(
            id=f"cplan-PLQB-{n}", school_id=school.school_id, fy=get_operational_fy()
        )
        CoreActivitySlot.objects.create(
            id=f"cslot-PLQB-{n}",
            core_plan=plan,
            school_id=school.school_id,
            intervention="leadership",
            activity_type="visit",
            sequence_number=1,
        )
        start = date(2026, 7, 6) + timedelta(days=7 * n)
        WeeklyFundRequest.objects.create(
            fy=FY,
            week_start_date=start,
            week_end_date=start + timedelta(days=6),
            responsible_user=user.id,
            total_amount=10_000,
            status="submitted_to_pl",
        )

    def _count(self):
        with CaptureQueriesContext(connection) as captured:
            get_todos(self.pl)
        return len(captured.captured_queries)

    def test_the_lead_s_queue_stays_within_its_ceiling_and_does_not_scale(self):
        baseline = self._count()
        self.assertLessEqual(baseline, self.CEILING)
        for _ in range(4):
            self._officer()
        grown = self._count()
        self.assertLessEqual(
            grown - baseline,
            self.GROWTH,
            f"a Programme Lead's /todos grew from {baseline} to {grown} queries "
            "for four more officers",
        )
