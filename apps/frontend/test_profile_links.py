"""A name that has a profile is a link to it, wherever it is written.

Owner, 2026-10-09: "clicking the cluster name or school name or district name
... can open the profile? The name should be a link to the profile
irrespective of where they are clicked from."
"""

from __future__ import annotations

import re
from pathlib import Path

from django.conf import settings
from django.contrib.auth.models import AnonymousUser
from django.template import Context, Template
from django.test import RequestFactory, TestCase

from apps.accounts.models import StaffProfile, User

TEMPLATES = Path(settings.BASE_DIR) / "templates"


class ProfileLinkTagTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.director = User.objects.create_user(
            email="links-cd@edify.org",
            name="Dora Director",
            roles=["CountryDirector"],
            active_role="CountryDirector",
            password="x",
            is_active=True,
        )
        StaffProfile.objects.create(user=cls.director, country="Uganda")

    def render(self, source, user=None, **values):
        request = RequestFactory().get("/")
        request.user = user or self.director
        return Template(source).render(Context({"request": request, **values}))

    def test_each_kind_of_name_opens_its_own_profile(self):
        for tag, path in (
            ("cluster_link", "/clusters/"),
            ("district_link", "/districts/"),
            ("sub_region_link", "/sub-regions/"),
            ("partner_link", "/partners/"),
            ("staff_link", "/staff/"),
        ):
            with self.subTest(tag=tag):
                html = self.render(
                    "{% " + tag + " name ref %}", name="North & South", ref="abc123"
                )
                self.assertIn(f'href="{path}abc123"', html)
                # The name is escaped, never trusted.
                self.assertIn(">North &amp; South</a>", html)

    def test_a_name_with_nothing_to_open_is_text(self):
        self.assertEqual(
            self.render("{% cluster_link name ref %}", name="North", ref=""), "North"
        )
        self.assertEqual(
            self.render("{% district_link name missing.id %}", name="Apac"), "Apac"
        )

    def test_no_name_writes_what_the_page_wrote_before(self):
        self.assertEqual(
            self.render('{% district_link name ref empty="—" %}', name="", ref="x"), "—"
        )
        self.assertEqual(
            self.render("{% cluster_link name ref %}", name=None, ref="x"), ""
        )

    def test_a_reader_who_cannot_open_the_profile_reads_text(self):
        html = self.render(
            "{% cluster_link name ref %}", user=AnonymousUser(), name="North", ref="abc"
        )

        self.assertEqual(html, "North")


class NamesAreWrittenThroughTheTagsTest(TestCase):
    """A ratchet: the plain forms the sweep of 2026-10-09 replaced do not
    come back in a table cell or a detail line. A name inside a form's tick
    list or a link of its own stays text, so those are not looked at."""

    PLAIN = re.compile(
        r">\s*\{\{\s*(?:\w+\.)*(?:cluster\.name|cluster_name|district\.name|"
        r"district_name|partner\.name|partner_name)\s*\}\}\s*</(?:td|th|dd)>"
    )
    #: Templates where the name is not a way in: exports and messages sent
    #: outside the platform.
    OUTSIDE = ("emails", "email", "pdf", "exports")

    def test_no_table_cell_writes_such_a_name_bare(self):
        bare = []
        for path in sorted(TEMPLATES.rglob("*.html")):
            relative = path.relative_to(TEMPLATES)
            if any(part in self.OUTSIDE for part in relative.parts):
                continue
            for match in self.PLAIN.finditer(path.read_text()):
                bare.append(f"{relative}: {match.group(0).strip()[:70]}")
        self.assertEqual(bare, [], "write these names with their link tag")
