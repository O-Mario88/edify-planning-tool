"""Reading a supervision page is not permission to delegate from it.

Cluster Oversight lives as a section on Team and Country Planning Oversight, so
IA, the Accountant and the RVP were given those pages to reach it. Widening a
page permission widens every route behind it, and these pages carry a "Send to
…" endpoint that opens a TeamAction against a named person.

Impact Assessment and the Accountant sit at the end of the chain, not above it:
IA verifies completed work, the Accountant confirms it and releases payment or
chases the accountability. Neither supervises anybody, so neither hands work
out. The RVP reads the country picture.

`send_risk_to_owner` constrains delegation with `within_staff_ids`, and the
view passes `scope.supervised_ids or None` — where None means *no constraint*.
A role that supervises nobody would therefore have been able to delegate to
anyone. These tests hold that line, and the matching one that the roles the
pages were built for can still send.
"""

from __future__ import annotations

from django.test import TestCase

from apps.accounts.models import StaffProfile, StaffSupervisorAssignment, User
from apps.core.rbac import EdifyRole
from apps.frontend.views.oversight_views import may_delegate


def _user(email, role):
    user = User.objects.create(
        email=email,
        name=email.split("@")[0],
        roles=[role.value],
        active_role=role.value,
        is_active=True,
    )
    StaffProfile.objects.create(user=user, title=role.value)
    return user


class WhoMayDelegateTest(TestCase):
    """The predicate, on its own, because both the endpoint and the template
    read it and they must not disagree about who sees a control."""

    def setUp(self):
        self.pl = _user("pl@access.test", EdifyRole.COUNTRY_PROGRAM_LEAD)
        self.cd = _user("cd@access.test", EdifyRole.COUNTRY_DIRECTOR)
        self.ia = _user("ia@access.test", EdifyRole.IMPACT_ASSESSMENT)
        self.accountant = _user("acc@access.test", EdifyRole.PROGRAM_ACCOUNTANT)
        self.rvp = _user("rvp@access.test", EdifyRole.REGIONAL_VICE_PRESIDENT)

    def test_the_team_page_belongs_to_the_programme_lead(self):
        self.assertTrue(may_delegate(self.pl, country=False))

    def test_the_country_page_belongs_to_the_country_director(self):
        self.assertTrue(may_delegate(self.cd, country=True))

    def test_verification_and_payment_roles_never_delegate(self):
        for user in (self.ia, self.accountant):
            with self.subTest(role=user.active_role):
                self.assertFalse(may_delegate(user, country=False))
                self.assertFalse(may_delegate(user, country=True))

    def test_the_rvp_reads_the_country_page_without_sending_from_it(self):
        self.assertFalse(may_delegate(self.rvp, country=True))

    def test_a_lead_does_not_gain_the_country_send(self):
        """Each page's delegation stays with the role it was built for."""
        self.assertFalse(may_delegate(self.pl, country=True))
        self.assertFalse(may_delegate(self.cd, country=False))


class TheSendEndpointsRefuseReadersTest(TestCase):
    """Over HTTP, because the predicate being right does not prove it is wired
    in — the endpoint is what a crafted POST reaches."""

    def setUp(self):
        self.pl = _user("pl2@access.test", EdifyRole.COUNTRY_PROGRAM_LEAD)
        self.ia = _user("ia2@access.test", EdifyRole.IMPACT_ASSESSMENT)
        self.accountant = _user("acc2@access.test", EdifyRole.PROGRAM_ACCOUNTANT)
        self.rvp = _user("rvp2@access.test", EdifyRole.REGIONAL_VICE_PRESIDENT)
        self.cceo = _user("cceo2@access.test", EdifyRole.CCEO)
        StaffSupervisorAssignment.objects.create(
            supervisee=self.cceo.staff_profile, supervisor=self.pl.staff_profile
        )

    def _post(self, user, url, data):
        """As the UI calls it. Without HX-Request the view answers with a
        redirect and a Django message, so the body is empty and an assertion
        about the refusal text would pass on any response at all."""
        self.client.force_login(user)
        return self.client.post(url, data, headers={"HX-Request": "true"})

    def test_ia_cannot_send_from_the_team_page(self):
        response = self._post(
            self.ia,
            "/team-planning-oversight/send",
            {"risk": "no_plan", "activity_id": "anything"},
        )

        body = response.content.decode().lower()
        self.assertNotIn("tracked under actions sent", body)
        self.assertIn("programme lead", body)

    def test_the_accountant_cannot_send_from_the_team_page(self):
        response = self._post(
            self.accountant,
            "/team-planning-oversight/send",
            {"risk": "no_plan", "activity_id": "anything"},
        )

        self.assertNotIn(
            "tracked under actions sent", response.content.decode().lower()
        )

    def test_the_rvp_cannot_send_from_the_country_page(self):
        response = self._post(
            self.rvp,
            "/country-planning-oversight/send",
            {"issue": "anything", "program_lead": self.pl.staff_profile_id},
        )

        body = response.content.decode().lower()
        self.assertNotIn("sent to", body)
        self.assertIn("country director", body)


class TheReadingRolesStillReachThePagesTest(TestCase):
    """The widening has to actually work, or the section they were given the
    page for is unreachable."""

    def setUp(self):
        self.ia = _user("ia3@access.test", EdifyRole.IMPACT_ASSESSMENT)
        self.accountant = _user("acc3@access.test", EdifyRole.PROGRAM_ACCOUNTANT)
        self.rvp = _user("rvp3@access.test", EdifyRole.REGIONAL_VICE_PRESIDENT)
        self.cceo = _user("cceo3@access.test", EdifyRole.CCEO)

    def _get(self, user, url):
        self.client.force_login(user)
        return self.client.get(url)

    def test_ia_and_the_accountant_open_the_team_page(self):
        for user in (self.ia, self.accountant):
            with self.subTest(role=user.active_role):
                response = self._get(user, "/team-planning-oversight/")
                self.assertEqual(response.status_code, 200)
                self.assertIn("Cluster Oversight", response.content.decode())

    def test_the_rvp_opens_the_country_page(self):
        response = self._get(self.rvp, "/country-planning-oversight/")

        self.assertEqual(response.status_code, 200)
        self.assertIn("Cluster Oversight", response.content.decode())

    def test_country_reading_roles_open_team_oversight_with_a_country_lens(self):
        for user in (self.ia, self.accountant, self.rvp):
            with self.subTest(role=user.active_role):
                response = self._get(user, "/team-planning-oversight/")
                self.assertEqual(response.status_code, 200)
                self.assertIn("Programme Lead", response.content.decode())

    def test_the_rvp_can_open_partner_oversight(self):
        response = self._get(self.rvp, "/partner-oversight/")

        self.assertEqual(response.status_code, 200)

    def test_a_cceo_still_reaches_neither(self):
        """The widening names three roles. It must not have opened the door."""
        for url in ("/team-planning-oversight/", "/country-planning-oversight/"):
            with self.subTest(url=url):
                self.assertIn(self._get(self.cceo, url).status_code, (302, 403))


class TheControlAgreesWithTheEndpointTest(TestCase):
    """A page must not offer what its endpoint refuses.

    The guard was added to the send views first and the templates still drew
    the buttons, so IA and the RVP saw a Send control that answered "not you".
    That is the same fault as a picker listing clusters the service rejects.
    """

    def setUp(self):
        self.cd = _user("cd4@access.test", EdifyRole.COUNTRY_DIRECTOR)
        self.rvp = _user("rvp4@access.test", EdifyRole.REGIONAL_VICE_PRESIDENT)
        self.pl = _user("pl4@access.test", EdifyRole.COUNTRY_PROGRAM_LEAD)
        self.ia = _user("ia4@access.test", EdifyRole.IMPACT_ASSESSMENT)

    def _body(self, user, url):
        self.client.force_login(user)
        return self.client.get(url).content.decode()

    def test_the_rvp_is_shown_no_country_send_form(self):
        body = self._body(self.rvp, "/country-planning-oversight/")

        self.assertNotIn('hx-post="/country-planning-oversight/send"', body)

    def test_the_country_director_still_sees_it(self):
        """The gate must refuse the reader without disarming the owner."""
        from apps.frontend.views.oversight_views import may_delegate

        self.assertTrue(may_delegate(self.cd, country=True))

    def test_neither_reader_is_shown_the_team_send_form(self):
        for user in (self.ia,):
            with self.subTest(role=user.active_role):
                body = self._body(user, "/team-planning-oversight/")
                self.assertNotIn('hx-post="/team-planning-oversight/send"', body)
