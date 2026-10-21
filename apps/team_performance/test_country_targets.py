"""Country targets: set by Impact Assessment or Admin only.

Owner, 2026-10-20: "All country target should be set by either IA or Admin",
on the Team Performance page, and the Country Director "No, IA and Admin
only". A target set here is the country's figure on every tab; a row left
empty falls back to the Uganda Master Priority Plan.
"""

from __future__ import annotations

from decimal import Decimal

from django.test import TestCase

from apps.audit.models import AuditLog
from apps.core.exceptions import BadRequest, Forbidden
from apps.team_performance import country_targets, measures
from apps.team_performance.targets import Scope, TargetBook
from apps.team_performance.test_ledger import make_officer

FY = "2031"


class CountryTargetTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.ia = make_officer("ia@tp-country.test", "ImpactAssessment")
        cls.admin = make_officer("admin@tp-country.test", "Admin")
        cls.cd = make_officer("cd@tp-country.test", "CountryDirector")
        cls.pl = make_officer("pl@tp-country.test", "Program Lead")

    def target(self, key):
        return TargetBook.load(FY).target(measures.get(key), Scope.country())

    def test_ia_sets_a_country_target_with_its_months(self):
        months = {m: Decimal(0) for m in range(1, 13)}
        months[1], months[2] = Decimal(60), Decimal(40)
        country_targets.save(self.ia, FY, {"core_visit_1": (Decimal(100), months)})

        target = self.target("core_visit_1")

        self.assertEqual(target.annual, 100)
        self.assertEqual(target.months[1], 60)
        self.assertEqual(target.through(2), 100)
        self.assertIn("Impact Assessment", target.source)

    def test_admin_may_set_and_the_director_and_a_lead_may_not(self):
        country_targets.save(self.admin, FY, {"msc": (Decimal(100), None)})
        self.assertEqual(self.target("msc").annual, 100)

        for user in (self.cd, self.pl):
            with self.assertRaises(Forbidden):
                country_targets.save(user, FY, {"msc": (Decimal(5), None)})
        self.assertEqual(self.target("msc").annual, 100)

    def test_the_months_must_add_up_to_the_year(self):
        months = {m: Decimal(0) for m in range(1, 13)}
        months[1] = Decimal(10)
        with self.assertRaises(BadRequest):
            country_targets.save(self.ia, FY, {"msc": (Decimal(100), months)})

    def test_a_target_cannot_be_negative(self):
        with self.assertRaises(BadRequest):
            country_targets.save(self.ia, FY, {"msc": (Decimal(-1), None)})

    def test_clearing_a_target_falls_back_to_the_plan(self):
        country_targets.save(self.ia, FY, {"msc": (Decimal(40), None)})
        country_targets.save(self.ia, FY, {"msc": (None, None)})

        self.assertIsNone(self.target("msc").annual)

    def test_every_change_is_audited_with_who_made_it(self):
        country_targets.save(self.ia, FY, {"msc": (Decimal(40), None)})

        entry = AuditLog.objects.filter(
            action="team_performance.country_target_set"
        ).last()
        self.assertEqual(entry.actor_id, str(self.ia.id))
        self.assertEqual(entry.subject_id, f"{FY}:msc")

    def test_a_region_still_reads_its_allocation_not_the_country_figure(self):
        country_targets.save(self.ia, FY, {"msc": (Decimal(40), None)})
        region = Scope.region(self.pl.staff_profile.id, set())

        target = TargetBook.load(FY).target(measures.get("msc"), region)

        self.assertIsNone(target.annual)


class CountryTargetPageTest(TestCase):
    URL = "/team-performance/country-targets/"

    @classmethod
    def setUpTestData(cls):
        cls.ia = make_officer("ia@tp-country-page.test", "ImpactAssessment")
        cls.cd = make_officer("cd@tp-country-page.test", "CountryDirector")

    def test_ia_opens_and_saves_the_editor(self):
        self.client.force_login(self.ia)
        page = self.client.get(self.URL, {"fy": FY})
        self.assertContains(page, 'name="annual:core_visit_1"')

        self.client.post(self.URL, {"fy": FY, "annual:core_visit_1": "120"})

        self.assertEqual(
            TargetBook.load(FY)
            .target(measures.get("core_visit_1"), Scope.country())
            .annual,
            120,
        )

    def test_one_save_sends_every_row_as_one_bundle(self):
        """Owner, 2026-10-20: "I want to update all the fields and save at
        once". One form; its ~1,950 boxes travel as one JSON field, inside
        Django's DATA_UPLOAD_MAX_NUMBER_FIELDS (a plain post of them all was
        refused with TooManyFieldsSent)."""
        import json
        import re

        from django.conf import settings

        self.client.force_login(self.ia)
        body = self.client.get(self.URL, {"fy": FY}).content.decode()
        self.assertEqual(len(re.findall(r"data-tp-targets-form", body)), 1)
        names = re.findall(r'name="((?:annual|m\d+):[^"]+)"', body)
        self.assertGreater(len(names), settings.DATA_UPLOAD_MAX_NUMBER_FIELDS)

        values = dict.fromkeys(names, "")
        values["annual:core_visit_1"] = "90"
        values["annual:msc"] = "12"
        values["m1:msc"], values["m2:msc"] = "5", "7"
        response = self.client.post(self.URL, {"fy": FY, "payload": json.dumps(values)})

        self.assertEqual(response.status_code, 302)
        book = TargetBook.load(FY)
        self.assertEqual(
            book.target(measures.get("core_visit_1"), Scope.country()).annual, 90
        )
        msc = book.target(measures.get("msc"), Scope.country())
        self.assertEqual((msc.annual, msc.through(2)), (12, 12))

    def test_a_bundle_that_cannot_be_read_saves_nothing(self):
        self.client.force_login(self.ia)

        page = self.client.post(self.URL, {"fy": FY, "payload": "{not json"})

        self.assertContains(page, "could not be read")
        self.assertIsNone(
            TargetBook.load(FY).target(measures.get("msc"), Scope.country()).annual
        )

    def test_a_large_target_reads_back_as_typed(self):
        self.client.force_login(self.ia)
        self.client.post(
            self.URL, {"fy": FY, "annual:government_core_participants": "1500000"}
        )

        page = self.client.get(self.URL, {"fy": FY})

        self.assertContains(page, 'value="1500000"')
        self.assertNotContains(page, "e+06")

    def test_an_error_names_the_row_not_its_key(self):
        self.client.force_login(self.ia)

        page = self.client.post(self.URL, {"fy": FY, "annual:msc": "10", "m1:msc": "3"})

        self.assertContains(page, "MSC Stories: the months add up to 3")
        self.assertNotContains(page, "msc: the months")

    def test_the_director_cannot_open_the_editor(self):
        self.client.force_login(self.cd)

        response = self.client.get(self.URL, {"fy": FY})

        self.assertNotContains(
            response, 'name="annual:core_visit_1"', status_code=response.status_code
        )

    def test_ia_reads_the_report(self):
        self.client.force_login(self.ia)

        self.assertEqual(self.client.get("/team-performance/").status_code, 200)
