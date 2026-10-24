"""A Core school's cohort: its year and cohort number (owner, 2026-10-24).

"Can we categorize core schools into cohort. Using the Year and the cohort
number ... it can only be set once ... it should be on the core school
profile in the edit school drawer." Answered the same day: users set it
directly in the Edit school drawer; choosing Core asks for the cohort number
and year; once saved it is locked, and only an Admin corrects it, every
change logged.
"""

from __future__ import annotations

from django.test import TestCase
from django.utils import timezone

from apps.accounts.models import StaffProfile, StaffSchoolAssignment, User
from apps.audit.models import AuditLog
from apps.geography.models import District, Region
from apps.schools import cohort
from apps.schools.models import School


def _user(email, role):
    user = User.objects.create_user(
        email=email,
        name=email.split("@")[0].title(),
        roles=[role],
        active_role=role,
        password="x",
        is_active=True,
    )
    return user, StaffProfile.objects.create(user=user, title=role)


class CoreCohortTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.region = Region.objects.create(name="Cohort Region")
        cls.district = District.objects.create(
            name="Cohort District", region=cls.region
        )
        cls.cceo, cls.cceo_sp = _user("cohort-cceo@t.org", "CCEO")
        cls.admin, _ = _user("cohort-admin@t.org", "Admin")
        cls.school = School.objects.create(
            school_id="COH-1",
            name="Cohort Primary",
            region=cls.region,
            district=cls.district,
            school_type="client",
            account_owner_id=cls.cceo_sp.id,
            account_owner_status="matched",
        )
        StaffSchoolAssignment.objects.create(staff=cls.cceo_sp, school_id=cls.school.id)

    def edit(self, user, **fields):
        self.client.force_login(user)
        data = {
            "school_id": "COH-1",
            "name": "Cohort Primary",
            "school_type": "client",
            "district_id": self.district.id,
            "account_owner_id": self.cceo_sp.id,
            **fields,
        }
        response = self.client.post(f"/schools/{self.school.id}/edit-drawer", data)
        self.school.refresh_from_db()
        return response.content.decode()

    def lock(self, year=2025, number=3):
        School.objects.filter(pk=self.school.pk).update(
            school_type="core",
            core_cohort_year=year,
            core_cohort_number=number,
            core_cohort_set_at=timezone.now(),
        )
        self.school.refresh_from_db()

    def test_choosing_core_asks_for_the_cohort(self):
        body = self.edit(self.cceo, school_type="core")

        self.assertIn("cohort", body.lower())
        self.assertIn('role="alert"', body)
        self.assertEqual(self.school.school_type, "client")
        self.assertIsNone(self.school.core_cohort_year)

    def test_a_core_school_saves_its_cohort_with_who_and_when(self):
        self.edit(
            self.cceo,
            school_type="core",
            core_cohort_year="2025",
            core_cohort_number="3",
        )

        self.assertEqual(self.school.school_type, "core")
        self.assertEqual(
            (self.school.core_cohort_year, self.school.core_cohort_number), (2025, 3)
        )
        self.assertEqual(self.school.core_cohort_set_by_id, self.cceo.id)
        self.assertIsNotNone(self.school.core_cohort_set_at)
        self.assertEqual(cohort.label(self.school), "Cohort 3 · 2025")
        entry = AuditLog.objects.get(action="school.cohort_set")
        self.assertEqual(entry.payload["cohort"], {"year": 2025, "number": 3})

    def test_a_year_or_number_out_of_range_is_refused(self):
        next_year = timezone.localdate().year + 1
        for year, number in (
            ("1999", "1"),
            (str(next_year + 1), "1"),
            ("2025", "0"),
            ("2025", "100"),
            ("twenty", "1"),
        ):
            with self.subTest(year=year, number=number):
                self.edit(
                    self.cceo,
                    school_type="core",
                    core_cohort_year=year,
                    core_cohort_number=number,
                )
                self.assertIsNone(self.school.core_cohort_year)

    def test_a_saved_cohort_is_locked_for_everyone_else(self):
        self.lock()

        body = self.edit(
            self.cceo,
            school_type="core",
            core_cohort_year="2026",
            core_cohort_number="1",
        )

        self.assertIn("locked", body.lower())
        self.assertEqual(
            (self.school.core_cohort_year, self.school.core_cohort_number), (2025, 3)
        )
        # The rest of the record still saves when the cohort is left alone.
        self.edit(self.cceo, school_type="core", name="Cohort Primary School")
        self.assertEqual(self.school.name, "Cohort Primary School")
        self.assertEqual(self.school.core_cohort_number, 3)

    def test_the_drawer_shows_a_locked_cohort_read_only(self):
        self.lock()
        self.client.force_login(self.cceo)

        body = self.client.get(
            f"/schools/{self.school.id}/edit-drawer"
        ).content.decode()

        self.assertIn("Cohort 3 · 2025", body)
        self.assertIn("data-cohort-locked", body)
        self.assertNotIn('name="core_cohort_year"', body)

    def test_an_admin_corrects_a_locked_cohort_and_it_is_logged(self):
        self.lock()

        self.edit(
            self.admin,
            school_type="core",
            core_cohort_year="2024",
            core_cohort_number="2",
        )

        self.assertEqual(
            (self.school.core_cohort_year, self.school.core_cohort_number), (2024, 2)
        )
        entry = AuditLog.objects.get(action="school.cohort_corrected")
        self.assertEqual(entry.payload["previous"], {"year": 2025, "number": 3})
        self.assertEqual(entry.payload["cohort"], {"year": 2024, "number": 2})

    def test_the_cohort_stays_when_the_school_moves_on_from_core(self):
        self.lock()

        self.edit(self.cceo, school_type="core_graduate")

        self.assertEqual(self.school.school_type, "core_graduate")
        self.assertEqual(cohort.label(self.school), "Cohort 3 · 2025")

    def test_another_type_asks_for_no_cohort(self):
        self.edit(self.cceo, school_type="champion", name="Champion Primary")

        self.assertEqual(self.school.school_type, "champion")
        self.assertIsNone(self.school.core_cohort_year)
        self.assertEqual(cohort.label(self.school), "")

    def test_the_school_profile_shows_the_cohort(self):
        self.lock()
        self.client.force_login(self.cceo)

        # The profile's overview card, and its Details tab.
        overview = self.client.get(f"/schools/{self.school.id}").content.decode()
        self.assertIn("Cohort 3 · 2025", overview)
        details = self.client.get(
            f"/schools/{self.school.id}", {"tab": "details"}
        ).content.decode()
        self.assertIn("data-school-cohort", details)
        self.assertIn("Cohort 3 · 2025", details)
