"""The comparison picker and its default selection must share reviewer scope."""

from unittest.mock import patch

from django.db.models import Q
from django.test import TestCase

from apps.accounts.models import User
from apps.activities.models import Activity
from apps.core.rbac import EdifyRole


class IACompareScopeTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(
            email="compare-scope@edify.test",
            name="Reviewer",
            roles=[EdifyRole.ADMIN.value],
            active_role=EdifyRole.ADMIN.value,
        )
        cls.other = Activity.objects.create(
            activity_type="school_visit",
            fy="2026",
            quarter="Q1",
            status="awaiting_ia_verification",
        )
        cls.allowed = Activity.objects.create(
            activity_type="school_visit",
            fy="2026",
            quarter="Q1",
            status="awaiting_ia_verification",
        )

    def setUp(self):
        self.client.force_login(self.user)
        self.scope = patch(
            "apps.frontend.views.ia_views._ia_reach_q",
            return_value=Q(id=self.allowed.id),
        )
        self.scope.start()
        self.addCleanup(self.scope.stop)

    def test_default_is_first_authorised_record(self):
        response = self.client.get("/ia/compare/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["act"].id, self.allowed.id)
        self.assertEqual(list(response.context["waiting_list"]), [self.allowed])

    def test_explicit_out_of_scope_record_remains_unavailable(self):
        response = self.client.get("/ia/compare/", {"activity_id": self.other.id})
        self.assertEqual(response.status_code, 404)


class IACompareLeavesLeadWorkTest(TestCase):
    """A CCEO's and a Programme Lead's staff work is verified by a lead, never
    by IA (owner, 2026-10-14: "IA does not verify CCEO and PL work"). IA's
    picker and its "awaiting IA" rollups leave it out, as its queue does."""

    @classmethod
    def setUpTestData(cls):
        from apps.accounts.models import StaffProfile

        cls.user = User.objects.create_user(
            email="compare-ia-reviewer@edify.test",
            name="Reviewer",
            roles=[EdifyRole.ADMIN.value],
            active_role=EdifyRole.ADMIN.value,
        )
        cls.work = {}
        for key, role in (
            ("cceo", EdifyRole.CCEO),
            ("lead", EdifyRole.COUNTRY_PROGRAM_LEAD),
            ("coordinator", EdifyRole.PROJECT_COORDINATOR),
        ):
            owner = User.objects.create(
                email=f"compare-{key}@edify.test",
                name=key.title(),
                roles=[role.value],
                active_role=role.value,
                is_active=True,
            )
            profile = StaffProfile.objects.create(
                user=owner, title=key.title(), country="Uganda"
            )
            cls.work[key] = Activity.objects.create(
                activity_type="school_visit",
                fy="2026",
                quarter="Q1",
                status="awaiting_ia_verification",
                delivery_type="staff",
                responsible_staff_id=profile.id,
            )
        cls.ids = [work.id for work in cls.work.values()]

    def setUp(self):
        self.client.force_login(self.user)
        self.scope = patch(
            "apps.frontend.views.ia_views._ia_reach_q",
            return_value=Q(id__in=self.ids),
        )
        self.scope.start()
        self.addCleanup(self.scope.stop)

    def test_the_picker_offers_only_work_ia_verifies(self):
        response = self.client.get("/ia/compare/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            list(response.context["waiting_list"]), [self.work["coordinator"]]
        )

    def test_awaiting_ia_rollups_leave_lead_work_out(self):
        from apps.frontend.views.ia_views import _ia_rollup_counts

        (row,) = _ia_rollup_counts(
            Activity.objects.filter(id__in=self.ids).values("fy")
        )
        self.assertEqual((row["planned"], row["waiting"]), (3, 1))
