"""The policy matrix is complete, and an acting capacity is never more than
the role it acts in.

A page or permission added to the Programme Lead or the Country Director
tomorrow must be named in ``apps.acting.policy`` as delegated or withheld
before an acting leader can hold it. These tests are what makes that so.
"""

from __future__ import annotations

from django.test import SimpleTestCase

from apps.acting.policy import (
    ACTING_COUNTRY_DIRECTOR,
    ACTING_PROGRAM_LEAD,
    ACTING_ROLES,
    ALL_AUTHORITIES,
    COMMON_WRITE_PAGES,
    DECISION_PAGES,
    PERSONAL_PAGES,
    Authority,
)
from apps.core.navigation import PAGE_PERMISSIONS, get_user_role_slug
from apps.core.rbac import ROLE_PERMISSIONS
from apps.core.rbac import Permission as P


class _Principal:
    is_authenticated = True

    def __init__(self, role):
        self.active_role = role


def _pages_of(role) -> set[str]:
    slug = get_user_role_slug(_Principal(role.value))
    return {page for page, roles in PAGE_PERMISSIONS.items() if slug in roles}


class PolicyCompletenessTests(SimpleTestCase):
    def test_every_permission_beyond_the_appointees_is_classified(self):
        for entry in ACTING_ROLES.values():
            beyond = set(ROLE_PERMISSIONS[entry.acting_role]) - set(
                ROLE_PERMISSIONS[entry.appointee_role]
            )
            named = entry.delegated_permissions | entry.withheld_permissions
            self.assertEqual(
                beyond - named,
                set(),
                f"{entry.label}: name these permissions as delegated or "
                "withheld in apps/acting/policy.py",
            )

    def test_every_page_beyond_the_appointees_is_classified(self):
        for entry in ACTING_ROLES.values():
            beyond = _pages_of(entry.acting_role) - _pages_of(entry.appointee_role)
            named = (
                entry.delegated_write_pages
                | entry.delegated_read_pages
                | entry.withheld_pages
            )
            self.assertEqual(
                beyond - named,
                set(),
                f"{entry.label}: name these pages as delegated or withheld "
                "in apps/acting/policy.py",
            )

    def test_nothing_is_both_delegated_and_withheld(self):
        for entry in ACTING_ROLES.values():
            self.assertFalse(entry.delegated_permissions & entry.withheld_permissions)
            self.assertFalse(
                (entry.delegated_write_pages | entry.delegated_read_pages)
                & entry.withheld_pages
            )
            self.assertFalse(entry.delegated_write_pages & entry.delegated_read_pages)

    def test_every_named_page_and_permission_exists(self):
        for entry in ACTING_ROLES.values():
            for page in (
                entry.delegated_write_pages
                | entry.delegated_read_pages
                | entry.withheld_pages
                | COMMON_WRITE_PAGES
            ):
                self.assertIn(page, PAGE_PERMISSIONS, f"{entry.label}: {page}")
            held = set(ROLE_PERMISSIONS[entry.acting_role])
            for key in entry.delegated_permissions:
                self.assertIn(key, held, f"{entry.label} delegates {key}")

    def test_only_the_two_approved_appointments_exist(self):
        self.assertEqual(
            {
                (e.appointee_role.value, e.acting_role.value)
                for e in ACTING_ROLES.values()
            },
            {("CCEO", "Program Lead"), ("Program Lead", "CountryDirector")},
        )


class WithheldTests(SimpleTestCase):
    """What no acting appointment carries, whatever is added later."""

    NEVER = {
        P.USER_MANAGE,
        P.STAFF_MANAGE,
        P.PARTNER_USER_MANAGE,
        P.SYSTEM_ADMIN,
        P.COST_SETTINGS_MANAGE,
        P.COUNTRY_BUDGET_SUBMIT,
        P.COUNTRY_BUDGET_APPROVE,
        P.FUND_REQUEST_APPROVE_ESCALATED,
        P.PLANNING_POLICY_MANAGE,
        P.STRATEGIC_PRIORITIES_APPROVE,
        P.MILESTONES_ALLOCATE,
        P.IA_VERIFY,
        P.PAYMENT_ACT,
    }

    def _effective(self, entry) -> set:
        return set(ROLE_PERMISSIONS[entry.acting_role]) - entry.withheld_permissions

    def test_no_acting_capacity_holds_administration_or_money_decisions(self):
        for entry in ACTING_ROLES.values():
            self.assertEqual(self._effective(entry) & self.NEVER, set(), entry.label)

    def test_every_authority_is_withheld_from_every_appointment(self):
        self.assertEqual(ALL_AUTHORITIES, {a.value for a in Authority})
        for entry in ACTING_ROLES.values():
            self.assertEqual(entry.withheld_authorities, ALL_AUTHORITIES)

    def test_personal_and_decision_pages_are_withheld_everywhere(self):
        for entry in ACTING_ROLES.values():
            self.assertLessEqual(PERSONAL_PAGES | DECISION_PAGES, entry.withheld_pages)

    def test_user_and_money_pages_are_withheld_from_an_acting_director(self):
        for page in (
            "users",
            "staff_setup_queue",
            "cost_settings",
            "country_budget",
            "consolidated_fund_allocation",
            "fy_planning_policy",
        ):
            self.assertIn(page, ACTING_COUNTRY_DIRECTOR.withheld_pages)
            self.assertFalse(ACTING_COUNTRY_DIRECTOR.may_write(page))

    def test_an_acting_director_reads_targets_and_distributes_none(self):
        """Priority monitoring is delegated; setting the targets is not."""
        entry = ACTING_COUNTRY_DIRECTOR
        self.assertIn("target_distribution", entry.delegated_read_pages)
        self.assertFalse(entry.may_write("target_distribution"))
        for key in (
            P.MILESTONES_DEFINE,
            P.MILESTONES_ALLOCATE,
            P.STRATEGIC_PRIORITIES_ALLOCATE,
            P.STRATEGIC_PRIORITIES_EDIT,
        ):
            self.assertIn(key, entry.withheld_permissions)
        self.assertIn("team_target_distribution", ACTING_PROGRAM_LEAD.withheld_pages)

    def test_an_acting_director_works_no_page_of_the_seat(self):
        """Every page of the country is read. What a director sends from one
        to follow up is named action by action, and nothing else is sent."""
        entry = ACTING_COUNTRY_DIRECTOR
        writable = {page for page in PAGE_PERMISSIONS if entry.may_write(page)}
        self.assertEqual(writable, set(COMMON_WRITE_PAGES))
        self.assertEqual(entry.delegated_write_pages, frozenset())
        # A follow-up is sent from a page that is otherwise read.
        self.assertTrue(
            entry.may_send("partner_oversight_send_action_view", ("partner_oversight",))
        )
        self.assertTrue(
            entry.may_send("planning_monitor_send_view", ("planning_monitor",))
        )
        # Decisions on the same pages are not.
        for decision in (
            "partner_allowance_grant_action",
            "partner_withdrawal_submit_view",
            "partner_bulk_withdrawal_view",
            "partner_withdrawal_review_view",
            "partner_verify_submit_view",
            "partner_return_resolve_submit_view",
        ):
            self.assertFalse(entry.may_send(decision, ("partner_oversight",)), decision)
        self.assertFalse(
            entry.may_send("training_ceiling_set_view", ("team_planning_oversight",))
        )
        # Nor a country-wide event, though the calendar is everyone's page.
        self.assertFalse(entry.may_send("calendar_event_create_view", ("calendar",)))
        # A follow-up action on a withheld page is still withheld.
        self.assertFalse(entry.may_send("follow_up_view", ("cost_settings",)))

    def test_decisions_beside_the_follow_up_stay_with_the_leader(self):
        """Owner, 2026-10-07: not all the privileges; their task is to manage
        and follow up with the team members."""
        lead, director = ACTING_PROGRAM_LEAD, ACTING_COUNTRY_DIRECTOR
        for entry in (lead, director):
            self.assertIn(P.PARTNER_HOLD, entry.withheld_permissions)
            self.assertIn(P.SCHOOL_EDIT, entry.withheld_permissions)
        self.assertFalse(
            lead.may_send("partner_allowance_grant_action", ("partner_oversight",))
        )
        # Managing the team is delegated: its reviews, its ceilings, its
        # follow-ups, and answering what its officers ask.
        self.assertIn(P.PARTNER_WITHDRAWAL_REVIEW, lead.delegated_permissions)
        for action, page in (
            ("pl_confirm_action", "pl_review_queue"),
            ("training_ceiling_set_view", "team_planning_oversight"),
            ("team_planning_send_action_view", "team_planning_oversight"),
            ("follow_up_create_view", "staff_activity"),
            ("coaching_record", "team_coaching"),
            ("partner_withdrawal_review_view", "partner_oversight"),
        ):
            self.assertTrue(lead.may_send(action, (page,)), action)
        for key in (
            P.PARTNER_ASSIGNMENT_WITHDRAW,
            P.PARTNER_WITHDRAWAL_REVIEW,
            P.SCHOOL_CLOSE,
            P.CLUSTER_ASSIGN,
            P.MANUAL_ACTIVITY_CREATE,
        ):
            self.assertIn(key, director.withheld_permissions)

    def test_every_named_action_is_a_real_view(self):
        """A renamed view must not silently fall out of the policy."""
        from django.urls import get_resolver

        names = set()

        def walk(resolver):
            for pattern in resolver.url_patterns:
                if hasattr(pattern, "url_patterns"):
                    walk(pattern)
                    continue
                view = getattr(pattern, "callback", None)
                while getattr(view, "__wrapped__", None) is not None:
                    view = view.__wrapped__
                names.add(getattr(view, "__name__", ""))

        walk(get_resolver())
        for entry in ACTING_ROLES.values():
            named = set(entry.follow_up_views or ()) | set(entry.withheld_views)
            self.assertEqual(named - names, set(), entry.label)

    def test_an_acting_lead_never_writes_a_read_only_or_withheld_page(self):
        entry = ACTING_PROGRAM_LEAD
        for page in entry.delegated_read_pages | entry.withheld_pages:
            self.assertFalse(entry.may_write(page), page)
        for page in entry.delegated_write_pages:
            self.assertTrue(entry.may_write(page), page)
        # A page the officer already works in their own role stays workable.
        self.assertTrue(entry.may_write("planning"))
