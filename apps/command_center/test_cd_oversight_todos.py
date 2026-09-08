"""What reaches the Country Director's queue.

Decisions routed to the CD used to arrive nowhere actionable: a returned FY
work plan produced no To-Do and its notice pointed at the wrong page, PL
monthly team requests reached the weekly advance page, missing catalogue
rates were shown only to Admin, an overdue escalation re-notified only the
RVP, a delegated-back decision produced nothing, and a quality flag was
raised in silence (owner, 2026-09-03).
"""

from __future__ import annotations

from datetime import date, timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from apps.accounts.models import StaffProfile
from apps.core.rbac import EdifyRole

User = get_user_model()


def _person(email, name, role):
    u = User.objects.create_user(
        email=email,
        name=name,
        roles=[role],
        active_role=role,
        password="x",
        is_active=True,
    )
    StaffProfile.objects.create(user=u, title=role, country="Uganda")
    return u


class CdOversightTodosTest(TestCase):
    def setUp(self):
        self.cd = _person("cdo-cd@t.org", "Dora CD", EdifyRole.COUNTRY_DIRECTOR.value)
        self.pl = _person(
            "cdo-pl@t.org", "Pat PL", EdifyRole.COUNTRY_PROGRAM_LEAD.value
        )

    def _ids(self, user):
        from apps.command_center.todo_service import get_todos

        return {t["id"]: t for t in get_todos(user)["todos"]}

    def test_a_returned_fy_work_plan_reaches_the_cd(self):
        from apps.monthly_work_plan.models import CountryAnnualBudget

        cab = CountryAnnualBudget.objects.create(
            fy="2026", country_id="Uganda", status="returned_by_rvp"
        )
        todo = self._ids(self.cd)[f"cab-cd-{cab.id}"]
        self.assertEqual(todo["action_url"], "/work-plan?view=fy")
        self.assertEqual(todo["priority"], "critical")

    def test_a_monthly_team_request_at_the_cd_stage_reaches_the_cd(self):
        from apps.fund_requests.models import FundRequest

        fr = FundRequest.objects.create(
            fy="2026",
            period="monthly",
            period_key="2026-M9",
            scope="team",
            submitted_by_user_id=self.pl.id,
            submitted_by_role="Program Lead",
            total_amount=250_000,
            activity_count=4,
            status="submitted_to_cd",
        )
        todo = self._ids(self.cd)[f"fr-cd-{fr.id}"]
        self.assertEqual(todo["action_url"], "/budget")
        self.assertNotIn(f"fr-cd-{fr.id}", self._ids(self.pl))

    def test_missing_catalogue_rates_reach_the_cd(self):
        from apps.activities.models import Activity
        from apps.geography.models import District, Region
        from apps.schools.models import School

        region = Region.objects.create(name="CDO Region")
        district = District.objects.create(name="CDO District", region=region)
        school = School.objects.create(
            school_id="CDO-1", name="CDO School", region=region, district=district
        )
        self.assertNotIn("cost-catalogue-missing-rates", self._ids(self.cd))
        Activity.objects.create(
            school=school,
            activity_type="school_visit",
            status="scheduled",
            fy="2026",
            cost_missing=True,
            scheduled_date=timezone.now() + timedelta(days=3),
            responsible_staff_id=self.pl.id,
        )
        todo = self._ids(self.cd)["cost-catalogue-missing-rates"]
        self.assertEqual(todo["action_url"], "/cost-settings")
        self.assertNotIn("cost-catalogue-missing-rates", self._ids(self.pl))

    def test_overdue_and_delegated_escalations_reach_the_cd(self):
        from apps.flags.models import LeadershipEscalation

        overdue = LeadershipEscalation.objects.create(
            raised_by_user_id=self.cd.id,
            category="structural_funding_gap",
            subject="Fuel shortfall",
            detail="x",
            severity="critical",
            status="open",
        )
        LeadershipEscalation.objects.filter(id=overdue.id).update(
            created_at=timezone.now() - timedelta(days=5)
        )
        delegated = LeadershipEscalation.objects.create(
            raised_by_user_id=self.cd.id,
            category="policy_exception_request",
            subject="Exception",
            detail="x",
            severity="normal",
            status="resolved",
            decision="delegated_back",
            resolved_at=timezone.now(),
        )
        ids = self._ids(self.cd)
        self.assertIn(f"esc-overdue-{overdue.id}", ids)
        self.assertIn(f"esc-delegated-{delegated.id}", ids)
        self.assertEqual(ids[f"esc-overdue-{overdue.id}"]["action_url"], "/escalations")

    def test_the_escalation_board_is_the_countrys_and_overdue_notifies_the_raiser(self):
        from apps.flags.escalation_service import sweep_overdue, visible_to
        from apps.flags.models import LeadershipEscalation
        from apps.notifications.models import Notification

        other_cd = _person("cdo-cd2@t.org", "Dan CD", EdifyRole.COUNTRY_DIRECTOR.value)
        esc = LeadershipEscalation.objects.create(
            raised_by_user_id=other_cd.id,
            category="other",
            subject="Raised by the other director",
            detail="x",
            severity="critical",
            status="open",
        )
        LeadershipEscalation.objects.filter(id=esc.id).update(
            created_at=timezone.now() - timedelta(days=5)
        )
        self.assertIn(esc.id, {e.id for e in visible_to(self.cd)})
        sweep_overdue()
        self.assertTrue(
            Notification.objects.filter(
                recipient_id=other_cd.id,
                source_event_type="leadership_escalation_overdue",
            ).exists()
        )

    def test_a_flag_reaches_the_pl_and_an_overdue_flag_comes_back_to_the_cd(self):
        from apps.flags.services import raise_flag
        from apps.notifications.models import Notification

        flag = raise_flag(
            {
                "assignedToUserId": self.pl.id,
                "category": "quality",
                "note": "Visit evidence is thin in Abim",
                "scopeName": "Abim",
                "dueDate": (date.today() - timedelta(days=2)).isoformat(),
            },
            self.cd,
        )
        self.assertTrue(
            Notification.objects.filter(
                recipient_id=self.pl.id, source_event_type="cd_flag_raised"
            ).exists()
        )
        self.assertIn(f"cdflag-{flag['id']}", self._ids(self.pl))
        self.assertIn(f"cdflag-overdue-{flag['id']}", self._ids(self.cd))

    def test_notification_routes_land_on_the_right_page(self):
        from apps.notifications.services import NotificationLinkResolver

        cases = {
            "annual_budget_returned": "/work-plan?view=fy",
            "monthly_team_request_submitted": "/budget",
            "cd_flag_raised": "/quality-checks",
            "leadership_escalation_overdue": "/escalations",
        }
        for event, route in cases.items():
            with self.subTest(event=event):
                got, _label = NotificationLinkResolver.resolve(
                    event, "X", "1", "CountryDirector"
                )
                self.assertEqual(got, route)

    def test_the_flags_page_has_a_menu_entry_for_the_cd_and_pl(self):
        from types import SimpleNamespace

        from apps.core.navigation import build_sidebar_for_user

        for role in ("CD", "PL"):
            urls = {
                i["url"]
                for g in build_sidebar_for_user(
                    SimpleNamespace(is_authenticated=True, active_role=role), "/"
                )
                for i in g["items"]
            }
            self.assertIn("/quality-checks", urls, role)
