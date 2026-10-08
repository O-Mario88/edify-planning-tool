"""The people the acting leadership tests are written about.

    Uganda
      Mary        Country Director
      John        Program Lead      Sarah, David, Michael (CCEOs)
      Peter       Program Lead      Agnes (CCEO)
      Hope        Human Resources
    Kenya
      Wanjiru     Country Director
      Otieno      Program Lead      Achieng (CCEO)

Every officer and Lead holds one school of their own, so a scope can be read
school by school. Dates are never frozen: a test names its day by patching
the one clock the feature reads (``on_day``), which leaves every library that
caches the real clock alone.
"""

from __future__ import annotations

import datetime
from contextlib import contextmanager
from unittest import mock

from django.test import TestCase

from apps.accounts.models import (
    StaffProfile,
    StaffSchoolAssignment,
    StaffSupervisorAssignment,
    User,
)
from apps.geography.models import District, Region
from apps.schools.models import School

SEPTEMBER_15 = datetime.date(2026, 9, 15)
SEPTEMBER_30 = datetime.date(2026, 9, 30)
OCTOBER_1 = datetime.date(2026, 10, 1)
OCTOBER_15 = datetime.date(2026, 10, 15)
OCTOBER_31 = datetime.date(2026, 10, 31)
NOVEMBER_1 = datetime.date(2026, 11, 1)
OCTOBER = "2026-10"
NOVEMBER = "2026-11"


@contextmanager
def on_day(day: datetime.date):
    """Run a block as though the platform's calendar read ``day``."""
    with (
        mock.patch("apps.acting.models.today", return_value=day),
        mock.patch("apps.acting.services.today", return_value=day),
        mock.patch("apps.acting.lifecycle.today", return_value=day),
    ):
        yield


def person(key, role, name, *, country="Uganda"):
    user = User.objects.create(
        id=f"act-{key}"[:30],
        email=f"act-{key}@edify.test",
        name=name,
        roles=[role],
        active_role=role,
        is_active=True,
    )
    profile = StaffProfile.objects.create(
        id=f"actsp-{key}"[:30],
        user=user,
        title=role,
        country=country,
        onboarding_state="active",
    )
    return user, profile


def fresh(user) -> User:
    """The account as a new request would load it."""
    return User.objects.select_related("staff_profile").get(id=user.id)


class ActingFixture(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.region = Region.objects.create(name="Acting Region", country="Uganda")
        cls.district = District.objects.create(
            name="Acting District", region=cls.region
        )
        cls.kenya_region = Region.objects.create(name="Acting Rift", country="Kenya")
        cls.kenya_district = District.objects.create(
            name="Acting Nakuru", region=cls.kenya_region
        )

        cls.mary, cls.mary_sp = person("mary", "CountryDirector", "Mary Director")
        cls.john, cls.john_sp = person("john", "Program Lead", "John Lead")
        cls.peter, cls.peter_sp = person("peter", "Program Lead", "Peter Lead")
        cls.hope, cls.hope_sp = person("hope", "HumanResources", "Hope People")
        cls.sarah, cls.sarah_sp = person("sarah", "CCEO", "Sarah Officer")
        cls.david, cls.david_sp = person("david", "CCEO", "David Officer")
        cls.michael, cls.michael_sp = person("michael", "CCEO", "Michael Officer")
        cls.agnes, cls.agnes_sp = person("agnes", "CCEO", "Agnes Officer")

        cls.wanjiru, cls.wanjiru_sp = person(
            "wanjiru", "CountryDirector", "Wanjiru Director", country="Kenya"
        )
        cls.otieno, cls.otieno_sp = person(
            "otieno", "Program Lead", "Otieno Lead", country="Kenya"
        )
        cls.achieng, cls.achieng_sp = person(
            "achieng", "CCEO", "Achieng Officer", country="Kenya"
        )

        for lead, officers in (
            (cls.john_sp, (cls.sarah_sp, cls.david_sp, cls.michael_sp)),
            (cls.peter_sp, (cls.agnes_sp,)),
            (cls.otieno_sp, (cls.achieng_sp,)),
        ):
            for officer in officers:
                StaffSupervisorAssignment.objects.create(
                    supervisor=lead, supervisee=officer
                )

        cls.schools = {}
        for key, profile, region, district in (
            ("john", cls.john_sp, cls.region, cls.district),
            ("sarah", cls.sarah_sp, cls.region, cls.district),
            ("david", cls.david_sp, cls.region, cls.district),
            ("michael", cls.michael_sp, cls.region, cls.district),
            ("peter", cls.peter_sp, cls.region, cls.district),
            ("agnes", cls.agnes_sp, cls.region, cls.district),
            ("otieno", cls.otieno_sp, cls.kenya_region, cls.kenya_district),
            ("achieng", cls.achieng_sp, cls.kenya_region, cls.kenya_district),
        ):
            school = School.objects.create(
                school_id=f"ACT-{key}",
                name=f"{key.title()} School",
                region=region,
                district=district,
                account_owner_id=profile.id,
            )
            StaffSchoolAssignment.objects.create(staff=profile, school_id=school.id)
            cls.schools[key] = school

    # ── Shorthand ───────────────────────────────────────────────────────────
    def appoint_sarah(self, month=OCTOBER, on=SEPTEMBER_15):
        from apps.acting import services

        with on_day(on):
            return services.appoint(
                fresh(self.john), appointee_staff_id=self.sarah_sp.id, month=month
            )

    def appoint_peter(self, month=OCTOBER, on=SEPTEMBER_15):
        from apps.acting import services

        with on_day(on):
            return services.appoint(
                fresh(self.mary), appointee_staff_id=self.peter_sp.id, month=month
            )

    def acting(self, user, on=OCTOBER_15):
        """The account as a request on ``on`` would present it."""
        from apps.acting import services

        loaded = fresh(user)
        with on_day(on):
            services.attach(loaded)
        return loaded
