"""One oversight format, on every oversight page (2026-09-16 brief).

Owner: "All Oversight Should have the same format. CD should also have the same
country oversight with all plans reflecting on the budget and the oversight
format having the same."

Team Oversight and Country Planning Oversight had each grown their own strip of
views. The same person moving between them had to relearn where things were,
and the two lenses added with this change would have had to be built twice. One
builder, one set of workspaces; each page passes its own base URL.

These pin the shared shape — the same lens names in the same order on both
pages, pointing at the page they were drawn on — and the two new lenses'
access, since a country portfolio is not a Programme Lead's to read.
"""

from __future__ import annotations

from pathlib import Path
from datetime import date

from django.test import SimpleTestCase, TestCase

from apps.accounts.models import StaffProfile, User
from apps.activities.models import Activity
from apps.clusters.models import Cluster
from apps.geography.models import District, Region, SubCounty
from apps.schools.models import School
from apps.frontend.views.oversight_views import (
    COUNTRY_OVERSIGHT_PATH,
    TEAM_OVERSIGHT_PATH,
    _lens_tabs,
)

ROOT = Path(__file__).resolve().parents[2]


def _read(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


class LensStripTest(SimpleTestCase):
    def test_both_pages_name_the_lenses_in_the_same_order(self):
        every = {"planning", "portfolio", "clusters", "coverage", "targets"}

        team = _lens_tabs(TEAM_OVERSIGHT_PATH, "planning", every)
        country = _lens_tabs(COUNTRY_OVERSIGHT_PATH, "planning", every)

        self.assertEqual(
            [tab["key"] for tab in team],
            ["planning", "portfolio", "coverage", "targets"],
        )
        self.assertEqual([t["key"] for t in team], [c["key"] for c in country])
        # Only the first differs, because "Team Plan" and "Country Plan" are
        # not the same plan.
        self.assertEqual(
            [t["label"] for t in team][1:], [c["label"] for c in country][1:]
        )

    def test_a_lens_links_to_the_page_it_was_drawn_on(self):
        """A tab that jumps a Programme Lead to the Country Director's page is
        a scope change dressed up as navigation."""
        tabs = _lens_tabs(TEAM_OVERSIGHT_PATH, "portfolio", {"planning", "portfolio"})

        for tab in tabs:
            self.assertTrue(tab["href"].startswith(TEAM_OVERSIGHT_PATH), tab)

    def test_the_active_lens_is_the_only_one_marked(self):
        tabs = _lens_tabs(TEAM_OVERSIGHT_PATH, "portfolio", {"planning", "portfolio"})

        self.assertEqual([t["key"] for t in tabs if t["is_active"]], ["portfolio"])

    def test_a_reader_with_one_lens_gets_no_strip(self):
        """A tab bar of one is furniture, and it costs the first table row its
        place above the fold."""
        self.assertEqual(_lens_tabs(TEAM_OVERSIGHT_PATH, "planning", {"planning"}), [])

    def test_both_new_lenses_carry_the_planned_budget(self):
        """Owner: "all plans reflecting on the budget". The portfolio carries
        the budget on its rows; the cluster lens, redesigned on 2026-09-19
        around seven operational columns, carries it as its headline tile."""
        portfolio = _read("templates/partials/oversight/portfolio_workspace.html")
        clusters = _read(
            "templates/partials/oversight/cluster_oversight_workspace.html"
        )
        table = _read("templates/partials/oversight/_cluster_table.html")

        self.assertIn("Planned budget", portfolio)
        self.assertIn("UGX {{", portfolio)
        self.assertIn("Cluster Budget", clusters)
        self.assertIn("UGX {{", clusters)
        for column in (
            "Cluster Name",
            "District",
            "# Schools",
            "Cluster Leader's Name",
            "Cluster Leader's Phone",
            "# School SSA Scores Avg",
            "Least Performing Intervention",
            "Date of Last Activity",
        ):
            self.assertIn(f">{column}</th>", table)

    def test_the_strip_is_one_shared_partial(self):
        """Two copies of it is how the two pages drifted apart the first time."""
        partial = _read("templates/partials/oversight/_lens_tabs.html")
        self.assertIn("{% for tab in lens_tabs %}", partial)

        for page in (
            "templates/pages/oversight/team_planning.html",
            "templates/pages/oversight/country_planning.html",
        ):
            body = _read(page)
            self.assertIn('{% include "partials/oversight/_lens_tabs.html" %}', body)
            # And no page keeps its own hand-rolled copy.
            self.assertNotIn('aria-label="Team oversight views"', body)


class LensAccessTest(TestCase):
    """Who reads which lens, checked through the routes rather than the flags."""

    def _a_cluster(self) -> Cluster:
        """One cluster, so the lens has a table rather than an empty state."""
        region = Region.objects.create(name="Lens Region")
        district = District.objects.create(name="Lens District", region=region)
        return Cluster.objects.create(
            name="Lens Cluster",
            region=region,
            district=district,
            sub_county=SubCounty.objects.create(name="Lens SC", district=district),
            status="active",
        )

    def _sign_in(self, email, role):
        user = User.objects.create_user(
            email=email, name=email, roles=[role], active_role=role, password="x"
        )
        StaffProfile.objects.create(user=user, country="Uganda")
        self.client.force_login(user)
        return user

    def test_district_filter_keeps_other_districts_available(self):
        director = self._sign_in("lens-district-cd@edify.org", "CountryDirector")
        region = Region.objects.create(name="District Choice Region")
        first = District.objects.create(name="District Choice One", region=region)
        second = District.objects.create(name="District Choice Two", region=region)
        for number, district in enumerate((first, second), 1):
            school = School.objects.create(
                school_id=f"CHOICE-{number}",
                name=f"Choice School {number}",
                region=region,
                district=district,
            )
            Activity.objects.create(
                activity_type="school_visit",
                school=school,
                fy="2026",
                planned_date=date(2026, 9, 21),
                status="scheduled",
                responsible_staff_id=str(director.id),
            )

        response = self.client.get(
            f"/country-planning-oversight/?fy=2026&district_id={first.id}"
        )

        self.assertEqual(response.status_code, 200)
        # The Filters disclosure is gone from the page (owner, 2026-09-25), but
        # a deep link still narrows by district and the choices are still
        # built before it does, so the other district stays available.
        self.assertEqual(response.context["advanced"].get("district_id"), first.id)
        districts = {
            pair[0] for pair in response.context["filter_options"]["districts"]
        }
        self.assertIn(first.id, districts)
        self.assertIn(second.id, districts)

    def test_impact_assessment_reads_the_country_portfolio(self):
        self._sign_in("lens-ia@edify.org", "ImpactAssessment")

        response = self.client.get("/team-planning-oversight/?view=portfolio")

        self.assertEqual(response.status_code, 200)
        body = response.content.decode()
        self.assertIn("Country portfolio", body)
        self.assertIn("Schools With No Plan", body)

    def test_a_programme_lead_reads_their_own_portfolio_called_that(self):
        """The lens is the same one, bounded by the reader's scope. A Programme
        Lead reading their own CCEOs' schools under a tab called "Country
        Portfolio" is being told something untrue about what they are seeing."""
        self._sign_in("lens-pl@edify.org", "Program Lead")

        body = self.client.get(
            "/team-planning-oversight/?view=portfolio"
        ).content.decode()

        self.assertIn("Team Portfolio", body)
        self.assertNotIn("Country Portfolio", body)
        self.assertIn("Team portfolio", body)

    def test_a_country_role_reads_the_same_lens_called_the_country(self):
        self._sign_in("lens-ia-label@edify.org", "ImpactAssessment")

        body = self.client.get(
            "/team-planning-oversight/?view=portfolio"
        ).content.decode()

        self.assertIn("Country Portfolio", body)
        self.assertNotIn("Team Portfolio", body)

    def test_the_accountant_keeps_a_page_with_no_strip_on_it(self):
        """They come here for the money in the plan, not for a programme lens.
        The same reasoning that gives them no coverage tab gives them no
        portfolio or cluster tab — and it is what keeps their first table row
        above the fold, which e2e/calm-workspace.spec.js measures."""
        self._sign_in("lens-accountant@edify.org", "Accountant")

        body = self.client.get("/team-planning-oversight/").content.decode()

        self.assertNotIn("data-edify-tablist", body)
        for lens in ("Country Portfolio", "Team Portfolio", "Cluster Performance"):
            self.assertNotIn(lens, body, lens)

    def test_the_country_director_reads_the_same_two_lenses(self):
        self._sign_in("lens-cd@edify.org", "CountryDirector")

        for view, marker in (("portfolio", "Country portfolio"),):
            with self.subTest(view=view):
                response = self.client.get(f"/country-planning-oversight/?view={view}")
                self.assertEqual(response.status_code, 200)
                self.assertIn(marker, response.content.decode())

    def test_the_country_directors_lenses_carry_the_budget(self):
        """Owner: "CD should also have the same country oversight with all
        plans reflecting on the budget"."""
        self._sign_in("lens-cd-budget@edify.org", "CountryDirector")
        self._a_cluster()

        portfolio = self.client.get(
            "/country-planning-oversight/?view=portfolio"
        ).content.decode()
        clusters = self.client.get("/cluster-oversight/").content.decode()

        self.assertIn("Portfolio Planned Budget", portfolio)
        self.assertIn("Cluster Budget", clusters)
        self.assertIn("UGX ", clusters)

    def test_the_cluster_lens_draws_its_seven_operational_columns(self):
        """The 2026-09-19 redesign replaced the activity-index ranking with
        seven columns a reader can act on; every one of them must be drawn."""
        self._sign_in("lens-ia-rank@edify.org", "ImpactAssessment")
        self._a_cluster()

        body = self.client.get("/cluster-oversight/").content.decode()

        for column in (
            "Cluster Name",
            "District",
            "Cluster Leader's Name",
            "Cluster Leader's Phone",
            "# School SSA Scores Avg",
            "Least Performing Intervention",
            "Date of Last Activity",
        ):
            self.assertIn(f">{column}</th>", body)

    def test_the_cluster_lens_groups_by_staff_and_drops_the_lead_column(self):
        """Owner, 2026-09-18: group by staff name so a Lead can monitor the
        individual, and drop the Programme Lead column. The 2026-09-19
        redesign keeps that shape: each officer is a tab holding their own
        clusters, so neither the Lead nor the responsible CCEO is a column,
        and District gets a column of its own."""
        self._sign_in("lens-ia-by-lead@edify.org", "ImpactAssessment")
        self._a_cluster()

        body = self.client.get("/cluster-oversight/").content.decode()

        self.assertIn('role="tablist"', body)
        self.assertIn(">District</th>", body)
        self.assertNotIn(">Programme Lead</th>", body)
        self.assertNotIn(">Responsible CCEO</th>", body)
        # One line per row rather than a cell that wraps to three.
        self.assertIn("edify-record-table w-full text-left whitespace-nowrap", body)

    def test_the_lenses_swap_in_place_for_htmx(self):
        """A filter change must replace the workspace, not the whole page."""
        self._sign_in("lens-ia-htmx@edify.org", "ImpactAssessment")

        response = self.client.get(
            "/team-planning-oversight/?view=portfolio", HTTP_HX_REQUEST="true"
        )

        body = response.content.decode()
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("<html", body)
        self.assertIn("Country portfolio", body)


class ActivityFamilyStripTest(SimpleTestCase):
    """A table each for visits, cluster meetings and group trainings.

    Owner, 2026-09-17: "Team oversight should have the table for planned school
    visits, a separate table for planned cluster meeting and a separate table
    for planned group training so that the managers (PLs) be able to see all
    the planned activities grouped by CCEOs in tabs."

    The per-CCEO grouping was already there; what a lead could not do was ask
    one question at a time. These pin the strip and, more importantly, that
    "all" is not one of the three — a page that only ever showed visits,
    meetings and trainings would silently drop programme events, SSA work and
    partner activities from a team's plan.
    """

    class _Item:
        def __init__(self, activity_type):
            self.activity_type = activity_type

    ITEMS = [
        _Item("school_visit"),
        _Item("core_visit"),
        _Item("cluster_meeting"),
        _Item("cluster_training"),
        _Item("in_school_training"),
        _Item("programme_event"),
        _Item("ssa_activity"),
    ]

    def test_the_strip_leads_with_everything_then_the_three_kinds(self):
        from apps.planning import oversight_service as oversight

        tabs = oversight.activity_tabs(self.ITEMS, "all")

        self.assertEqual(
            [(tab["key"], tab["label"]) for tab in tabs],
            [
                ("all", "All Activities"),
                ("visits", "School Visits"),
                ("meetings", "Cluster Meetings"),
                ("trainings", "Group Trainings"),
            ],
        )

    def test_each_tab_carries_the_count_its_table_will_draw(self):
        from apps.planning import oversight_service as oversight

        tabs = {
            tab["key"]: tab["count"]
            for tab in oversight.activity_tabs(self.ITEMS, "all")
        }

        self.assertEqual(tabs["all"], len(self.ITEMS))
        self.assertEqual(tabs["visits"], 2)
        self.assertEqual(tabs["meetings"], 1)
        self.assertEqual(tabs["trainings"], 2)
        for key, count in tabs.items():
            self.assertEqual(
                count,
                len(oversight.in_family(self.ITEMS, key)),
                f"the {key} tab counts what its table draws",
            )

    def test_no_kind_of_work_falls_off_the_page(self):
        """A programme event and an SSA activity are in none of the three."""
        from apps.planning import oversight_service as oversight

        three = set()
        for key in ("visits", "meetings", "trainings"):
            three.update(id(item) for item in oversight.in_family(self.ITEMS, key))

        self.assertLess(len(three), len(self.ITEMS))
        self.assertEqual(len(oversight.in_family(self.ITEMS, "all")), len(self.ITEMS))

    def test_an_unknown_family_shows_everything_rather_than_nothing(self):
        from apps.planning import oversight_service as oversight

        self.assertEqual(
            len(oversight.in_family(self.ITEMS, "not-a-family")), len(self.ITEMS)
        )

    def test_the_strip_is_a_comment_tag_not_a_hash_comment(self):
        """Django's `{# #}` is single-line: a multi-line one renders as text,
        and did — a paragraph of rationale appeared above the tabs."""
        workspace = _read("templates/partials/oversight/pl_workspace.html")

        self.assertIn('aria-label="Activity type"', workspace)
        self.assertNotIn(
            "{# ── What kind of work, within that person's plan\n", workspace
        )
