"""The Blocked Closures directory lists the longest-blocked first.

The model has no ordering, so the page listed blockers in whatever order the
query plan produced (owner, 2026-11-18: longest blocked first). The Go gateway
draws the page in the same order.
"""

from __future__ import annotations

from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from apps.accounts.models import StaffProfile
from apps.activities.models import Activity, ClosureBlocker
from apps.geography.models import District, Region
from apps.schools.models import School


class BlockedClosureOrderTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user(
            email="closure-order@edify.test",
            password="password123",
            name="Closure Order",
            roles=["Admin"],
            active_role="Admin",
            is_active=True,
        )
        StaffProfile.objects.create(id="closure-order-staff", user=cls.user)
        region = Region.objects.create(name="Closure Order Region")
        district = District.objects.create(name="Closure Order District", region=region)
        school = School.objects.create(
            school_id="CLOSURE-ORDER-SCHOOL",
            name="Closure Order School",
            region=region,
            district=district,
        )
        now = timezone.now()
        # Filed newest first, so table order and blocked order disagree.
        for days, reason in (
            (1, "Newest blocker"),
            (30, "Middle blocker"),
            (90, "Oldest blocker"),
        ):
            activity = Activity.objects.create(
                activity_type="visit",
                school=school,
                status="closed",
                responsible_staff_id=cls.user.user_id,
            )
            ClosureBlocker.objects.create(
                activity=activity,
                blocking_reason=reason,
                responsible_role="CCEO",
                created_at=now - timedelta(days=days),
            )

    def setUp(self):
        self.client.force_login(self.user)

    def test_the_longest_blocked_comes_first(self):
        body = self.client.get("/activities/closure/blocked").content.decode()

        oldest, middle, newest = (
            body.index(reason)
            for reason in ("Oldest blocker", "Middle blocker", "Newest blocker")
        )
        self.assertLess(oldest, middle)
        self.assertLess(middle, newest)
