"""The schedule drawer must reach the browser as one intact form.

INC-000003 ("JavaScript exception on /planning") was not a script bug. A dead
{% if reschedule_mode %} wrapper left its closing </div> outside the condition,
so the rendered payload carried one more </div> than it opened inside the
<form>. Django rendered it without complaint and the server answered 200 — but
the browser's parser, on the surplus close, pops the open-element stack past
the form and silently ends it. Everything below that point became the form's
SIBLING: Alpine evaluated :value="delivery" outside the x-data scope that
defines it (the ReferenceError the defect beacon reported), delivery_type and
the goal were never submitted, and the Schedule button lost its form owner —
the drawer's primary action did nothing at all.

Status codes and template syntax checks are blind to this whole class, which
is why these tests walk the served HTML the way a browser would: the div depth
inside a form must never go negative, and the controls the workflow depends on
must sit between <form> and its true close.
"""

from __future__ import annotations

import re

from django.test import Client, TestCase

from apps.accounts.models import User
from apps.geography.models import District, Region
from apps.schools.models import School

FORM_OPEN = re.compile(r"<form\b")
DIV = re.compile(r"<div\b|</div>")


def _form_region(html: str) -> str:
    """The payload between the drawer form's open tag and its close tag."""
    start = FORM_OPEN.search(html)
    assert start, "no <form> in the drawer payload"
    end = html.index("</form>", start.start())
    return html[start.start() : end]


def _min_div_depth(fragment: str) -> int:
    depth = lowest = 0
    for match in DIV.finditer(fragment):
        depth += 1 if match.group(0) == "<div" else -1
        lowest = min(lowest, depth)
    return lowest


class ScheduleDrawerDomIntegrityTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        region = Region.objects.create(name="Drawer Test Region")
        district = District.objects.create(name="Drawer Test District", region=region)
        cls.school = School.objects.create(
            school_id="DRAWER-DOM-1",
            name="Drawer DOM School",
            region=region,
            district=district,
        )
        # Admin: full authority and platform-wide scope, so the drawer opens
        # for a school no field assignment covers. The DOM structure under
        # test is identical for every role.
        cls.user = User.objects.create(
            id="drawer-dom-admin",
            email="drawer-dom@edify.org",
            name="Drawer DOM Admin",
            roles=["Admin"],
            active_role="Admin",
            is_active=True,
            status="active",
        )

    def _drawer(self, path: str) -> str:
        client = Client()
        client.force_login(self.user)
        response = client.get(path, HTTP_HX_REQUEST="true")
        self.assertEqual(response.status_code, 200)
        return response.content.decode("utf-8")

    def test_no_surplus_close_ends_the_form_early(self):
        html = self._drawer(
            f"/planning/schedule-modal?school_id={self.school.school_id}"
        )
        self.assertGreaterEqual(
            _min_div_depth(_form_region(html)),
            0,
            "a </div> with no matching open inside the form makes the browser "
            "close the form early — every field and button after it stops "
            "belonging to it",
        )

    def test_the_controls_the_workflow_needs_are_inside_the_form(self):
        html = self._drawer(
            f"/planning/schedule-modal?school_id={self.school.school_id}"
        )
        region = _form_region(html)
        # The Alpine binding that raised INC-000003, the fields that silently
        # stopped submitting, and the submit control that went dead.
        for needle in (
            'name="delivery_type"',
            'name="activity_purpose_text"',
            'name="focus_intervention"',
            "</button>",
        ):
            self.assertIn(needle, region, f"{needle} fell outside the form")

    def test_every_alpine_identifier_the_form_binds_is_declared(self):
        """:value="delivery" outside x-data is a ReferenceError in every
        browser and invisible to every server-side check."""
        html = self._drawer(
            f"/planning/schedule-modal?school_id={self.school.school_id}"
        )
        region = _form_region(html)
        # Alpine scopes nest, and the date picker declares its own x-data
        # inside the form's — so an identifier is fine if ANY x-data block in
        # the payload declares it. What this catches is the INC-000003 class:
        # an identifier declared nowhere at all, which every browser turns
        # into a ReferenceError.
        blocks = re.findall(r'x-data="\{(.*?)\}"', region, re.S)
        self.assertTrue(blocks, "the drawer form declares no x-data")
        names = set()
        for block in blocks:
            names.update(re.findall(r"(\w+)\s*:", block))
            # A getter is a declaration too. Reading `get projectIntervention()`
            # as undeclared would fail the drawer for using the one construct
            # that keeps derived values derived.
            names.update(re.findall(r"\bget\s+(\w+)\s*\(", block))
        for bound in re.findall(r':value="(\w+)"', region):
            self.assertIn(
                bound,
                names,
                f':value="{bound}" is bound to nothing any x-data declares',
            )

    def test_assign_partner_drawer_holds_together_too(self):
        html = self._drawer(
            f"/planning/assign-partner-modal?school_id={self.school.school_id}"
        )
        self.assertGreaterEqual(_min_div_depth(_form_region(html)), 0)
