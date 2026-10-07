"""A school taken back from a partner leaves the partner (owner, 2026-10-06).

"all withdrawn schools from the partner or project does not leave the partner
or project it remains with the status returned. it should leave the list or
tables where they have been withdrawn. It also does not update the counts, and
summaries where they are counted."

A withdrawal ends the hand-over at ``returned_to_staff`` and records what
happens next. Every reader that listed hand-overs by partner alone went on
listing it: Partner Monitoring showed it under "Returned" and counted its
school as assigned, the Partners page counted it as waiting for a date, the
project's page kept the partner's name beside the school, the partner's own
scope still held the school, and a visit the partner had dated stayed in the
planned figures after it was called off.

A hand-back nobody has decided on is a different thing: somebody still has to
say what happens to the school, so it stays where that decision is made.
"""

from __future__ import annotations

from datetime import date, timedelta

from apps.activities.models import Activity
from apps.core.rbac import EdifyRole
from apps.core.scoping import resolve_user_scope, scope_cache_fingerprint
from apps.partners import withdrawal_service
from apps.partners.models import PartnerAssignment
from apps.partners.support_responsibility import left_partner_q, released_q
from apps.partners.withdrawal_models import WithdrawalDisposition, WithdrawalReason
from apps.planning import oversight_service as planning_oversight
from apps.planning import partner_oversight_service as svc
from apps.planning.test_partner_oversight import PartnerOversightFixture

EXPLANATION = "Handed over by mistake; the officer will visit the school."


def payload(**over):
    base = {
        "reason_category": WithdrawalReason.INCORRECT_ASSIGNMENT,
        "partner_facing_reason": EXPLANATION,
        "disposition": WithdrawalDisposition.RETURN_TO_PLANNING,
    }
    base.update(over)
    return base


class _Fixture(PartnerOversightFixture):
    def withdraw(self, assignment, **over):
        withdrawal_service.withdraw(assignment.id, payload(**over), self.pl_user)
        assignment.refresh_from_db()
        return assignment

    def hand_back(self, assignment):
        """The partner lets the work go; no staff member has decided yet."""
        assignment.status = PartnerAssignment.STATUS_RETURNED_TO_STAFF
        assignment.return_reason = "No capacity this term."
        assignment.save(update_fields=["status", "return_reason", "updated_at"])
        return assignment


class TheRuleTest(_Fixture):
    def test_a_withdrawn_hand_over_has_left_the_partner(self):
        assignment = self.withdraw(self.assign())

        self.assertEqual(assignment.status, PartnerAssignment.STATUS_RETURNED_TO_STAFF)
        self.assertTrue(assignment.is_released)
        self.assertTrue(assignment.has_left_partner)
        self.assertTrue(
            PartnerAssignment.objects.filter(
                left_partner_q(), id=assignment.id
            ).exists()
        )

    def test_a_hand_back_nobody_has_decided_is_released_but_still_listed(self):
        assignment = self.hand_back(self.assign())

        self.assertTrue(assignment.is_released)
        self.assertFalse(assignment.has_left_partner)
        self.assertFalse(
            PartnerAssignment.objects.filter(
                left_partner_q(), id=assignment.id
            ).exists()
        )
        self.assertTrue(
            PartnerAssignment.objects.filter(released_q(), id=assignment.id).exists()
        )

    def test_work_still_with_the_partner_is_neither(self):
        assignment = self.assign()

        self.assertFalse(assignment.is_released)
        self.assertFalse(assignment.has_left_partner)

    def test_the_legacy_spellings_have_left_too(self):
        for status in ("returned", "cancelled"):
            with self.subTest(status=status):
                self.assertTrue(PartnerAssignment(status=status).has_left_partner)


class PartnerMonitoringTest(_Fixture):
    def test_a_withdrawn_school_is_not_a_row_of_the_partner_s_table(self):
        kept = self.assign()
        self.withdraw(self.assign(school=self.rival_school))

        items = svc.build_items(self.pl_user, fy=self.fy)

        self.assertEqual([i.partner_assignment_id for i in items], [kept.id])
        self.assertFalse([i for i in items if i.is_returned])

    def test_the_counts_follow_the_rows(self):
        self.assign()
        self.withdraw(self.assign(school=self.rival_school))

        items = svc.build_items(self.pl_user, fy=self.fy)
        summary = svc.summarize(items)
        line = svc.monitoring_summary(items)

        self.assertEqual(summary["schools_assigned"], 1)
        self.assertEqual(summary["awaiting_schedule"], 1)
        self.assertEqual(summary["returned"], 0)
        self.assertEqual(line["assigned"], 1)
        self.assertEqual(line["returned"], 0)

    def test_a_partner_left_with_nothing_is_not_an_active_partner(self):
        self.withdraw(self.assign())

        items = svc.build_items(self.pl_user, fy=self.fy)

        self.assertEqual(items, [])
        self.assertEqual(svc.summarize(items)["active_partners"], 0)

    def test_a_hand_back_waiting_on_a_decision_is_listed_and_not_counted_assigned(
        self,
    ):
        waiting = self.hand_back(self.assign())

        items = svc.build_items(self.pl_user, fy=self.fy)
        summary = svc.summarize(items)

        self.assertEqual([i.partner_assignment_id for i in items], [waiting.id])
        self.assertTrue(items[0].awaits_staff_decision)
        self.assertEqual(summary["returned"], 1)
        self.assertEqual(summary["schools_assigned"], 0)
        self.assertEqual(summary["active_partners"], 0)
        # The line above the table counts its rows, this one among them.
        line = svc.monitoring_summary(items)
        self.assertEqual((line["assigned"], line["returned"]), (1, 1))

    def test_once_decided_the_hand_back_leaves_as_well(self):
        from apps.partners.services import resolve_returned_assignment

        waiting = self.hand_back(self.assign())
        resolve_returned_assignment(
            waiting.id,
            {"resolution": PartnerAssignment.RESOLUTION_STAFF_DELIVERY},
            self.pl_user,
        )

        self.assertEqual(svc.build_items(self.pl_user, fy=self.fy), [])

    def test_a_recalled_visit_takes_its_row_and_its_money_with_it(self):
        assignment = self.assign()
        activity = self.schedule(assignment, cost=180_000)

        before = svc.summarize(svc.build_items(self.pl_user, fy=self.fy))
        self.withdraw(assignment)
        items = svc.build_items(self.pl_user, fy=self.fy)
        after = svc.summarize(items)

        self.assertEqual(before["scheduled"], 1)
        self.assertEqual(before["scheduled_budget"], 180_000)
        self.assertEqual(items, [])
        self.assertEqual(after["scheduled"], 0)
        self.assertEqual(after["scheduled_budget"], 0)
        activity.refresh_from_db()
        self.assertEqual(activity.status, "cancelled")

    def test_the_school_s_own_page_no_longer_lists_the_partner(self):
        self.withdraw(self.assign())

        self.assertEqual(svc.build_items_for_school(self.school.id), [])

    def test_the_school_s_page_still_shows_a_hand_back_to_decide(self):
        waiting = self.hand_back(self.assign())

        items = svc.build_items_for_school(self.school.id)

        self.assertEqual([i.partner_assignment_id for i in items], [waiting.id])


class PlanningOversightTest(_Fixture):
    """Planning Oversight and Core Schools Oversight list hand-overs the
    partner has not dated. One taken back read "Partner yet to schedule"."""

    def _waiting(self):
        return planning_oversight._unscheduled_assignments_in_scope(
            planning_oversight.resolve_oversight_scope(self.pl_user), fy=None
        )

    def test_a_withdrawn_hand_over_is_not_waiting_on_the_partner(self):
        kept = self.assign()
        self.withdraw(self.assign(school=self.rival_school))

        self.assertEqual([row.id for row in self._waiting()], [kept.id])

    def test_a_hand_back_to_decide_is_still_there(self):
        waiting = self.hand_back(self.assign())

        self.assertEqual([row.id for row in self._waiting()], [waiting.id])


class PartnersPageTest(_Fixture):
    """/partners: the partner's schools, visits and what still needs a date.
    The page of the roles that hold Partners and not Partner Monitoring (the
    Project Coordinator among them); everybody else is sent to Monitoring."""

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.coordinator, _profile = cls._staff(
            "pc@p.test", "Coordinator", EdifyRole.PROJECT_COORDINATOR
        )

    def setUp(self):
        self.client.force_login(self.coordinator)

    def _page(self):
        response = self.client.get(f"/partners?partner={self.partner.id}&fy={self.fy}")
        self.assertEqual(response.status_code, 200)
        return response

    def test_a_withdrawn_school_is_not_listed_or_counted(self):
        self.assign(school=self.rival_school)
        self.assertContains(self._page(), "Rival School")
        self.withdraw(self.assign())

        page = self._page()

        self.assertContains(page, "Rival School")
        self.assertNotContains(page, "School A")

    def test_a_visit_called_off_with_the_withdrawal_is_not_listed(self):
        assignment = self.assign()
        self.schedule(assignment, when=date.today() + timedelta(days=8))
        self.assertContains(self._page(), "School A")

        self.withdraw(assignment)

        self.assertNotContains(self._page(), "School A")


class PartnerProfileTest(_Fixture):
    def setUp(self):
        self.client.force_login(self.pl_user)

    def _profile(self):
        page = self.client.get(f"/partners/{self.partner.id}")
        self.assertEqual(page.status_code, 200)
        return page

    def test_work_taken_back_is_not_in_the_partner_s_record(self):
        assignment = self.assign()
        self.schedule(assignment)
        self.assertContains(self._profile(), "School A")

        self.withdraw(assignment)

        self.assertNotContains(self._profile(), "School A")


class PartnerScopeTest(_Fixture):
    """What the partner's own users may read: the schools they hold."""

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        from apps.accounts.models import User

        cls.partner_user = User.objects.create(
            email="officer@partner.test",
            name="Partner Officer",
            roles=[EdifyRole.PARTNER_FIELD_OFFICER.value],
            active_role=EdifyRole.PARTNER_FIELD_OFFICER.value,
            is_active=True,
        )
        cls.partner.user_id = cls.partner_user.id
        cls.partner.save(update_fields=["user_id"])

    def _schools(self):
        return set(resolve_user_scope(self.partner_user).school_ids)

    def test_a_withdrawn_school_leaves_the_partner_s_scope(self):
        self.assign()
        gone = self.assign(school=self.rival_school)
        self.assertEqual(self._schools(), {self.school.id, self.rival_school.id})

        self.withdraw(gone)

        self.assertEqual(self._schools(), {self.school.id})

    def test_a_school_handed_back_leaves_it_too(self):
        self.hand_back(self.assign())

        self.assertEqual(self._schools(), set())

    def test_cached_figures_are_filed_under_the_schools_held(self):
        """A partner owns no school, so nothing else in the fingerprint names
        what it reaches: without them a withdrawn school stayed in its cached
        figures until they lapsed."""
        kept = self.assign()
        gone = self.assign(school=self.rival_school)
        before = scope_cache_fingerprint(resolve_user_scope(self.partner_user))

        self.withdraw(gone)
        after = scope_cache_fingerprint(resolve_user_scope(self.partner_user))

        self.assertNotEqual(before, after)
        self.assertTrue(PartnerAssignment.objects.filter(id=kept.id).exists())


class CalledOffWorkIsNotPlannedTest(_Fixture):
    """A visit the partner had dated is cancelled when the school is taken
    back. It is the record of that decision, not planned work."""

    def test_the_team_roster_does_not_count_it(self):
        from apps.hr.team_roster import build_team_roster

        assignment = self.assign()
        self.schedule(assignment)
        before = build_team_roster(self.pl_user, self.fy)

        self.withdraw(assignment)
        after = build_team_roster(self.pl_user, self.fy)

        def planned(roster):
            return sum(row["delivery"]["planned"] for row in roster["rows"])

        self.assertEqual(planned(before), 1)
        self.assertEqual(planned(after), 0)

    def test_the_programme_lead_s_analytics_do_not_count_it(self):
        from apps.analytics.pl_analytics_service import (
            _team_activity_qs,
            resolve_pl_scope,
        )

        assignment = self.assign()
        activity = self.schedule(assignment)
        pls = resolve_pl_scope(self.pl_user, {})
        self.assertIn(
            activity.id,
            set(_team_activity_qs(pls, self.fy, None, {}).values_list("id", flat=True)),
        )

        self.withdraw(assignment)

        self.assertNotIn(
            activity.id,
            set(_team_activity_qs(pls, self.fy, None, {}).values_list("id", flat=True)),
        )

    def test_its_cost_is_not_money_allocated(self):
        from apps.activities.models import ActivityScheduleCostLine
        from apps.core.activity_types import NON_FUNDABLE_ACTIVITY_STATUSES

        assignment = self.assign()
        activity = self.schedule(assignment, cost=180_000)
        self.withdraw(assignment)

        live = ActivityScheduleCostLine.objects.filter(
            activity__fy=self.fy, activity__deleted_at__isnull=True
        ).exclude(activity__status__in=NON_FUNDABLE_ACTIVITY_STATUSES)

        self.assertTrue(
            ActivityScheduleCostLine.objects.filter(activity=activity).exists(),
            "the cost lines stay as the record",
        )
        self.assertFalse(live.filter(activity=activity).exists())
        self.assertEqual(Activity.objects.get(id=activity.id).status, "cancelled")
