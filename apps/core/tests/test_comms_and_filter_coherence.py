"""Access is re-checked at read time, and a KPI describes its own table.

The messaging gaps that sat behind the fail-open context gate: the recipient
rule had no relationship term, the API read paths did not revalidate the way
the page path does, the inbox emitted a subject and body extract without
re-checking, and only the primary context was authorised while linked items
were not. Plus the filter/KPI disagreement — a filtered table under an
unfiltered headline.
"""

from __future__ import annotations

import inspect

from django.test import TestCase

from apps.accounts.models import (
    StaffProfile,
    StaffSchoolAssignment,
    StaffSupervisorAssignment,
    User,
)
from apps.core.permissions import RolePermissionService
from apps.core.rbac import EdifyRole
from apps.geography.models import District, Region
from apps.schools.models import School


def _user(email, name, role):
    return User.objects.create_user(
        email=email,
        name=name,
        roles=[role],
        active_role=role,
        password="pw12345678",
        is_active=True,
        status="active",
    )


class RecipientRelationshipTests(TestCase):
    """The rule was a role-pair matrix with no relationship term."""

    @classmethod
    def setUpTestData(cls):
        cls.pl_a = _user("mr-pla@t.org", "PL A", EdifyRole.COUNTRY_PROGRAM_LEAD.value)
        cls.pl_b = _user("mr-plb@t.org", "PL B", EdifyRole.COUNTRY_PROGRAM_LEAD.value)
        cls.sp_a = StaffProfile.objects.create(user=cls.pl_a, country="Uganda")
        cls.sp_b = StaffProfile.objects.create(user=cls.pl_b, country="Uganda")

        cls.mine = _user("mr-mine@t.org", "My CCEO", EdifyRole.CCEO.value)
        cls.theirs = _user("mr-theirs@t.org", "Their CCEO", EdifyRole.CCEO.value)
        cls.sp_mine = StaffProfile.objects.create(user=cls.mine, country="Uganda")
        cls.sp_theirs = StaffProfile.objects.create(user=cls.theirs, country="Uganda")
        StaffSupervisorAssignment.objects.create(
            supervisee=cls.sp_mine, supervisor=cls.sp_a
        )
        StaffSupervisorAssignment.objects.create(
            supervisee=cls.sp_theirs, supervisor=cls.sp_b
        )

    def test_a_pl_may_message_their_own_cceo(self):
        self.assertTrue(
            RolePermissionService.can_message_recipient(self.pl_a, self.mine)
        )

    def test_a_pl_may_not_message_another_pls_cceo(self):
        self.assertFalse(
            RolePermissionService.can_message_recipient(self.pl_a, self.theirs),
            "once the context gate passed, any PL could reach any other PL's team",
        )

    def test_a_pl_may_still_reach_peers_and_leadership(self):
        cd = _user("mr-cd@t.org", "CD One", EdifyRole.COUNTRY_DIRECTOR.value)
        self.assertTrue(RolePermissionService.can_message_recipient(self.pl_a, cd))
        self.assertTrue(
            RolePermissionService.can_message_recipient(self.pl_a, self.pl_b)
        )


class ReadTimeRevalidationTests(TestCase):
    """The page path re-checks on every open; its API siblings did not."""

    def test_the_api_thread_read_revalidates_context(self):
        from apps.messaging import services

        source = inspect.getsource(services.thread)
        self.assertIn("can_access_context", source)

    def test_recent_revalidates_before_returning_bodies(self):
        from apps.messaging import services

        source = inspect.getsource(services.recent)
        self.assertIn(
            "can_access_context",
            source,
            "this returned the last fifty message bodies with no re-check",
        )

    def test_the_inbox_revalidates_before_emitting_a_snippet(self):
        from apps.messaging import services

        source = inspect.getsource(services.threads_for_user)
        self.assertIn(
            "can_access_context",
            source,
            "a user who lost the record kept seeing the subject and a "
            "ninety-character body extract; only the click refused",
        )


class LinkedItemAuthorizationTests(TestCase):
    """Only the primary context was ever checked."""

    def test_context_summary_authorises_each_linked_item(self):
        from apps.messaging import services

        source = inspect.getsource(services.context_summary)
        self.assertIn("can_access_context(user, context_type, item_id)", source)

    def test_send_drops_unauthorised_linked_items(self):
        from apps.messaging import services

        source = inspect.getsource(services.send)
        self.assertIn("can_access_context(sender, context_type, item_id)", source)


class FilteredKpiAgreementTests(TestCase):
    """A KPI must describe the population beneath it."""

    @classmethod
    def setUpTestData(cls):
        region = Region.objects.create(name="KPI Region")
        other_region = Region.objects.create(name="Other Region")
        cls.district = District.objects.create(name="KPI District", region=region)
        cls.other_district = District.objects.create(
            name="Other District", region=other_region
        )
        for i in range(3):
            School.objects.create(
                name=f"In Scope {i}",
                school_id=f"KPI-{i}",
                region_id=region.id,
                district_id=cls.district.id,
                school_type="client",
            )
        for i in range(5):
            School.objects.create(
                name=f"Elsewhere {i}",
                school_id=f"OTH-{i}",
                region_id=other_region.id,
                district_id=cls.other_district.id,
                school_type="client",
            )
        cls.admin = _user("kpi-admin@t.org", "Admin", EdifyRole.ADMIN.value)

    def test_school_directory_kpis_follow_the_filter(self):
        self.client.force_login(self.admin)
        unfiltered = self.client.get("/schools").context["kpi_strip_items"]
        filtered = self.client.get(
            f"/schools?district={self.district.id}"
        ).context["kpi_strip_items"]

        def _total(items):
            for item in items:
                if "total" in item["label"].lower():
                    return int(str(item["value"]).replace(",", ""))
            return None

        self.assertEqual(_total(unfiltered), 8)
        self.assertEqual(
            _total(filtered),
            3,
            "the headline ignored every filter, so a one-district table sat "
            "under an org-wide total",
        )

    def test_ia_queue_kpis_are_computed_after_filtering(self):
        from apps.frontend.views import ia_views

        source = inspect.getsource(ia_views.ia_verification_queue_view)
        waiting = source.index("waiting_count = ")
        first_filter = source.index("filtered_qs = filtered_qs.filter")
        self.assertGreater(
            waiting,
            first_filter,
            "the KPI block ran before the filters were even read",
        )
