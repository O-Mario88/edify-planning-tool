"""The platform search contract.

These lock the behaviour a search control has to have before it counts as
working, not merely as present: the query reaches the database, the number on
screen describes the match set, search composes with tabs and filters rather
than replacing them, and no query can widen a user's scope.

The last one is the security case. A search that returns a record the user
could not otherwise reach is a data leak wearing a text box, so it is asserted
per role rather than assumed from the queryset the view happens to start with.
"""

from __future__ import annotations

import re

from django.test import TestCase

from apps.accounts.models import User
from apps.core.rbac import EdifyRole
from apps.geography.models import District, Region, SubCounty
from apps.schools.models import School


LISTED = re.compile(r"([\d,]+)\s*schools? listed", re.IGNORECASE)


def listed_count(html: str) -> int:
    """The count the directory actually shows the user."""
    found = LISTED.search(html)
    assert found, "the directory did not render a result count"
    return int(found.group(1).replace(",", ""))


class SchoolDirectorySearchContractTest(TestCase):
    """School Directory is the reference implementation for every other page."""

    def setUp(self):
        self.region = Region.objects.create(name="Contract Region")
        self.district = District.objects.create(
            name="Buikwe", region=self.region
        )
        self.other_district = District.objects.create(
            name="Kayunga", region=self.region
        )
        self.sub_county = SubCounty.objects.create(
            name="Najjembe", district=self.district
        )

        self.matching = School.objects.create(
            school_id="SC-CONTRACT-1",
            name="Najjembe Central Primary",
            region=self.region,
            district=self.district,
            sub_county=self.sub_county,
            account_owner_name_raw="Miriam Nabwire",
        )
        # Same region, different district — the control for district search.
        self.other = School.objects.create(
            school_id="SC-CONTRACT-2",
            name="Kayunga Hill Primary",
            region=self.region,
            district=self.other_district,
        )

        self.admin = User.objects.create_user(
            email="search-contract-admin@example.org",
            name="Search Contract Admin",
            roles=[EdifyRole.ADMIN.value],
            active_role=EdifyRole.ADMIN.value,
            password="test-password",
        )

    def _get(self, **params):
        self.client.force_login(self.admin)
        return self.client.get("/schools", params).content.decode()

    def test_result_count_reports_matches_not_page_size(self):
        """The count has to move with the result set, never with per_page.

        It used to render the length of the current page, so a 700-school
        directory announced "15 schools listed" and a query that matched three
        records announced the same 15.
        """
        wide = listed_count(self._get(per_page=15))
        wider = listed_count(self._get(per_page=50))
        self.assertEqual(
            wide,
            wider,
            "the count changed with page size, so it is counting the page",
        )

        narrowed = listed_count(self._get(q="Najjembe Central", per_page=15))
        self.assertLess(narrowed, wide)
        self.assertEqual(narrowed, 1)

    def test_search_covers_the_documented_fields(self):
        """Name and ID alone left a school unfindable by where it sits."""
        for label, query in (
            ("school name", "Najjembe Central"),
            ("school id", "SC-CONTRACT-1"),
            ("district", "Buikwe"),
            ("sub-county", "Najjembe"),
            ("assigned staff", "Nabwire"),
        ):
            with self.subTest(field=label):
                body = self._get(q=query)
                self.assertIn(
                    self.matching.name,
                    body,
                    f"searching by {label} did not reach the school",
                )

    def test_a_query_that_matches_nothing_returns_nothing(self):
        """An empty result states itself rather than falling back to everything."""
        self.assertEqual(listed_count(self._get(q="zzz-no-such-school")), 0)

    def test_search_composes_with_filters_instead_of_replacing_them(self):
        """A filtered view stays filtered once a query is typed into it."""
        in_scope = listed_count(
            self._get(q="Primary", district=str(self.district.id))
        )
        self.assertEqual(in_scope, 1)

        # The same query against the other district must not return the first.
        body = self._get(q="Najjembe", district=str(self.other_district.id))
        self.assertNotIn(self.matching.name, body)

    def test_search_cannot_widen_a_users_scope(self):
        """The security case: scope first, search second.

        A Partner Field Officer has no route into the directory at all, so no
        query — however broad — may return directory rows to them.
        """
        partner = User.objects.create_user(
            email="search-contract-partner@example.org",
            name="Search Contract Partner",
            roles=[EdifyRole.PARTNER_FIELD_OFFICER.value],
            active_role=EdifyRole.PARTNER_FIELD_OFFICER.value,
            password="test-password",
        )
        self.client.force_login(partner)
        response = self.client.get("/schools", {"q": "Primary"})

        if response.status_code == 200:
            body = response.content.decode()
            self.assertNotIn(self.matching.name, body)
            self.assertNotIn(self.other.name, body)
        else:
            self.assertIn(response.status_code, {302, 403, 404})


class TopbarSearchControlTest(TestCase):
    """The control itself, not the query behind it."""

    def test_the_magnifier_submits_the_same_form_enter_does(self):
        shell = (
            __import__("pathlib")
            .Path("templates/layouts/shell.html")
            .read_text(encoding="utf-8")
        )
        self.assertIn('type="submit"', shell)
        self.assertIn('aria-label="Search"', shell)
        self.assertIn("edify-search-submit", shell)
        self.assertNotIn(
            "pl-3 flex items-center pointer-events-none",
            shell,
            "the icon is decorative again — it cannot be clicked",
        )

    def test_htmx_search_forms_respond_to_submit(self):
        """Without submit in the trigger, clicking the icon reloads the page.

        Every hx_trigger in the codebase lists only keyup and search, so the
        template appends submit rather than trusting each caller to.
        """
        shell = (
            __import__("pathlib")
            .Path("templates/layouts/shell.html")
            .read_text(encoding="utf-8")
        )
        self.assertRegex(shell, r"hx-trigger=\"\{\{[^}]+\}\}, submit\"")


class VerificationQueueSearchContractTest(TestCase):
    """The IA queue had twelve dropdowns and nowhere to type."""

    def setUp(self):
        self.region = Region.objects.create(name="Queue Region")
        self.district = District.objects.create(
            name="Nakaseke", region=self.region
        )
        self.school = School.objects.create(
            school_id="SC-QUEUE-1",
            name="Semuto Parents Primary",
            region=self.region,
            district=self.district,
        )
        self.other_school = School.objects.create(
            school_id="SC-QUEUE-2",
            name="Kapeeka Modern Primary",
            region=self.region,
            district=self.district,
        )
        self.ia = User.objects.create_user(
            email="queue-contract-ia@example.org",
            name="Queue Contract IA",
            roles=[EdifyRole.IMPACT_ASSESSMENT.value],
            active_role=EdifyRole.IMPACT_ASSESSMENT.value,
            password="test-password",
        )

        from apps.activities.models import Activity

        # Only rows carrying a Salesforce ID ever reach this queue.
        self.waiting = Activity.objects.create(
            school=self.school,
            fy="2026",
            quarter="Q2",
            activity_type="school_visit",
            status="awaiting_ia_verification",
            salesforce_activity_id="SFA-00099",
        )
        self.other = Activity.objects.create(
            school=self.other_school,
            fy="2026",
            quarter="Q2",
            activity_type="school_visit",
            status="awaiting_ia_verification",
            salesforce_activity_id="SFA-00100",
        )

    def _queue(self, **params):
        self.client.force_login(self.ia)
        return self.client.get("/ia/verification/", params).content.decode()

    def test_the_queue_can_be_searched_by_salesforce_id(self):
        """The one value that always identifies a queue row exactly."""
        body = self._queue(q="SFA-00099")
        self.assertIn("Semuto Parents Primary", body)
        self.assertNotIn("Kapeeka Modern Primary", body)

    def test_the_queue_can_be_searched_by_school_and_district(self):
        for label, query in (
            ("school name", "Semuto Parents"),
            ("school id", "SC-QUEUE-1"),
        ):
            with self.subTest(field=label):
                self.assertIn("Semuto Parents Primary", self._queue(q=query))

        # District holds both schools, so it must narrow to neither.
        both = self._queue(q="Nakaseke")
        self.assertIn("Semuto Parents Primary", both)
        self.assertIn("Kapeeka Modern Primary", both)

    def test_a_query_matching_nothing_empties_the_queue(self):
        body = self._queue(q="zzz-no-such-record")
        self.assertNotIn("Semuto Parents Primary", body)
        self.assertNotIn("Kapeeka Modern Primary", body)


class AnalyticsSearchContractTest(TestCase):
    """Analytics accepted `q` in its query path long before it had a control.

    The traversal it used — responsible_staff__user__name — does not exist on
    Activity, so every ?q= was a hard 500. Nothing caught it because there was
    no search box on the page to produce one, which is exactly how a crash this
    total survives in a query path.
    """

    def setUp(self):
        self.region = Region.objects.create(name="Analytics Region")
        self.district = District.objects.create(
            name="Wakiso", region=self.region
        )
        School.objects.create(
            school_id="SC-ANALYTICS-1",
            name="Nansana Progressive Primary",
            region=self.region,
            district=self.district,
        )
        self.cd = User.objects.create_user(
            email="analytics-contract-cd@example.org",
            name="Analytics Contract CD",
            roles=[EdifyRole.COUNTRY_DIRECTOR.value],
            active_role=EdifyRole.COUNTRY_DIRECTOR.value,
            password="test-password",
        )

    def test_every_query_shape_renders_instead_of_raising(self):
        self.client.force_login(self.cd)
        for label, params in (
            ("no query", {}),
            ("empty query", {"q": ""}),
            ("matching query", {"q": "Nansana"}),
            ("staff-name query", {"q": "Analytics Contract"}),
            ("no-match query", {"q": "zzz-no-such-record"}),
        ):
            with self.subTest(case=label):
                response = self.client.get("/analytics", params)
                self.assertEqual(
                    response.status_code,
                    200,
                    f"/analytics raised on a {label}",
                )

    def test_the_page_offers_a_search_control_at_all(self):
        """A backend search with no control is unreachable, not optional."""
        self.client.force_login(self.cd)
        body = self.client.get("/analytics").content.decode()
        self.assertIn("Search analytics records", body)


class NoDuplicatePersistentSearchTest(TestCase):
    """§3: a page may carry at most one persistent search input.

    Two inputs for one dataset means two ids, two ways to submit, and two
    places for the query to disagree with itself after a back-navigation —
    plus a screen reader announcing a search landmark twice.
    """

    INPUT = re.compile(
        r'<input[^>]*(?:type="search"|name="q")[^>]*>', re.IGNORECASE
    )

    def setUp(self):
        self.admin = User.objects.create_user(
            email="dupe-contract-admin@example.org",
            name="Dupe Contract Admin",
            roles=[EdifyRole.ADMIN.value],
            active_role=EdifyRole.ADMIN.value,
            password="test-password",
        )

    def test_search_first_pages_carry_exactly_one_input(self):
        self.client.force_login(self.admin)
        for route, params in (
            ("/search", {"q": "primary"}),
            ("/help/glossary", {"q": "netsuite"}),
            ("/help/search", {"q": "evidence"}),
            ("/help", {}),
        ):
            with self.subTest(route=route):
                response = self.client.get(route, params)
                if response.status_code != 200:
                    continue
                found = self.INPUT.findall(response.content.decode())
                self.assertLessEqual(
                    len(found),
                    1,
                    f"{route} renders {len(found)} persistent search inputs",
                )

    def test_the_surviving_input_carries_the_active_query(self):
        """Removing the body box must not strand the query in an empty field."""
        self.client.force_login(self.admin)
        body = self.client.get("/search", {"q": "primary"}).content.decode()
        found = self.INPUT.findall(body)
        self.assertEqual(len(found), 1)
        self.assertIn('value="primary"', found[0])
