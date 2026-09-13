"""The demo seed hands its sample portfolio to cceo@edify.org on every database.

The holder used to be the first CCEO by ``order_by("user__email")``, and
Postgres collations disagree about "cceo@…" against "cceo1@…": macOS's en_US
sorts cceo@edify.org first, glibc's en_US and C sort it after cceo19@edify.org.
On Linux — every CI runner — all 700 sample schools went to cceo10@edify.org,
and the account the demo and the browser suite sign in as opened an empty
School Directory, Core Schools list, cluster board and priority portfolio. The
browser journeys that walk those pages failed on every run from 2026-09-09
while passing on the Mac they were written on.
"""

from io import StringIO

from django.core.management import call_command
from django.test import TestCase, override_settings

from apps.accounts.models import StaffProfile, StaffSchoolAssignment, User
from apps.core.rbac import EdifyRole
from apps.schools.models import School


@override_settings(IS_PRODUCTION=False)
class SeedPrimaryCceoTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        # A CCEO whose address sorts ahead of every demo account under any
        # collation, so an email sort fails here on every machine, not only
        # where the database happens to collate like glibc.
        early = User.objects.create(
            email="a.cceo@edify.org",
            name="Early CCEO",
            roles=[EdifyRole.CCEO.value],
            active_role=EdifyRole.CCEO.value,
            is_active=True,
        )
        StaffProfile.objects.create(user=early, title="CCEO")
        call_command("seed", "--demo", stdout=StringIO(), stderr=StringIO())

    def test_the_primary_demo_cceo_holds_every_sample_school(self):
        primary = StaffProfile.objects.get(user__email="cceo@edify.org")
        samples = School.objects.filter(source="local_test_upload")
        self.assertEqual(samples.count(), 700)
        self.assertEqual(
            StaffSchoolAssignment.objects.filter(staff=primary).count(),
            samples.count(),
        )
        self.assertFalse(samples.exclude(account_owner_id=primary.id).exists())

    def test_no_other_cceo_is_handed_the_sample_portfolio(self):
        self.assertFalse(
            StaffSchoolAssignment.objects.exclude(
                staff__user__email="cceo@edify.org"
            ).exists()
        )
