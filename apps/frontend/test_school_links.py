"""A school's name is the way into its profile, wherever it is shown.

Owner, 2026-10-08: "schools profile is only linked to school name in the
school directory i need it linked to school names everywhere". One tag writes
the name (`apps.frontend.templatetags.school_links`), available to every
template without a ``{% load %}``:

* it links for a reader the School pages let in, by either identifier a
  school has, and writes plain text for one they refuse (a partner) or where
  the row holds no school;
* a name is data: it is escaped, and so is the reference in the address;
* the shared identity tag (ID beside the name) links the name the same way,
  and stays out of the way where it already sits inside a link.

The pages are checked by crawling them as each role; these tests hold the
tag's own behaviour.
"""

from __future__ import annotations

from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from django.template import Context, Template
from django.test import RequestFactory, TestCase

User = get_user_model()


def _user(uid, role):
    return User.objects.create(
        id=uid,
        email=f"{uid}@edify.org",
        name=uid,
        roles=[role],
        active_role=role,
        is_active=True,
    )


class SchoolLinkTagTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.cceo = _user("sl-cceo", "CCEO")
        cls.partner = _user("sl-partner", "PartnerFieldOfficer")

    def render(self, source, user, **values):
        request = RequestFactory().get("/planning")
        request.user = user
        return Template(source).render(Context({"request": request, **values}))

    def test_a_name_links_to_the_profile_without_a_load(self):
        html = self.render(
            "{% school_link name ref %}", self.cceo, name="Hill Primary", ref="1598"
        )
        self.assertEqual(
            html,
            '<a href="/schools/1598" class="school-link hover:underline" '
            "data-school-link>Hill Primary</a>",
        )

    def test_either_identifier_is_a_reference(self):
        html = self.render(
            "{% school_link name ref %}",
            self.cceo,
            name="Hill Primary",
            ref="cmuhe3chx00aeo2ddkjv1",
        )
        self.assertIn('href="/schools/cmuhe3chx00aeo2ddkjv1"', html)

    def test_a_reader_the_school_pages_refuse_gets_the_name_as_text(self):
        for user in (self.partner, AnonymousUser()):
            html = self.render(
                "{% school_link name ref %}", user, name="Hill Primary", ref="1598"
            )
            self.assertEqual(html, "Hill Primary")

    def test_no_school_to_open_is_plain_text(self):
        for ref in (None, "", "  "):
            html = self.render(
                "{% school_link name ref %}", self.cceo, name="Hill Primary", ref=ref
            )
            self.assertEqual(html, "Hill Primary")
        self.assertEqual(
            self.render("{% school_link name ref %}", self.cceo, name="", ref="1"), ""
        )

    def test_the_name_and_the_reference_are_escaped(self):
        html = self.render(
            "{% school_link name ref %}",
            self.cceo,
            name='<script>alert("x")</script> & Sons',
            ref='a b/"c"?d',
        )
        self.assertNotIn("<script>", html)
        self.assertIn("&lt;script&gt;", html)
        self.assertIn("&amp; Sons", html)
        self.assertIn('href="/schools/a%20b%2F%22c%22%3Fd"', html)

    def test_a_page_may_add_its_own_classes(self):
        html = self.render(
            '{% school_link name ref "font-semibold" %}',
            self.cceo,
            name="Hill Primary",
            ref="1598",
        )
        self.assertIn('class="school-link hover:underline font-semibold"', html)

    def test_the_identity_tag_links_the_name_beside_its_id(self):
        source = "{% load school_identity %}{% school_identity name code=code %}"
        html = self.render(source, self.cceo, name="Hill Primary", code="1598")
        self.assertIn(
            '<span class="school-list-id" title="School ID">1598</span>', html
        )
        self.assertIn('<a href="/schools/1598"', html)
        self.assertIn(">Hill Primary</a>", html)
        # Where it already sits inside a link, or the page gives this reader
        # none, it writes the name only.
        plain = self.render(
            "{% load school_identity %}{% school_identity name code=code link=False %}",
            self.cceo,
            name="Hill Primary",
            code="1598",
        )
        self.assertNotIn("<a ", plain)
        self.assertIn("Hill Primary", plain)
        # And a partner gets no link from it either.
        partner = self.render(source, self.partner, name="Hill Primary", code="1598")
        self.assertNotIn("<a ", partner)
