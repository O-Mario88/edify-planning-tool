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
