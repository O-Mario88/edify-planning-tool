"""My Plan's fiscal year, quarter and month filters nest.

Owner, 2026-09-17: "when I select an FY, it should automatically load the data
for that FY. When I select quarter for example Q1, it should load the first
month of that quarter … selecting month should load the data for that month.
But if I only filter FY2027, it should give me all the data, all visits for
that FY should be loaded but sorted by date in ascending order by default."

Two things had to be true at once. A bare fiscal year had to mean the whole
fiscal year — it used to mean "the current week of it". And picking a wider
filter had to clear the narrower ones it contains, because a GET form submits
every select, not only the one that changed: switching to FY2027 with October
still selected would otherwise have loaded one month of a year the user had
just asked to see all of.
"""

from __future__ import annotations

from datetime import date

from django.contrib.auth import get_user_model
from django.test import TestCase

from apps.accounts.models import StaffProfile
from apps.activities.models import Activity
from apps.core.fy import get_quarter_for_date
from apps.geography.models import District, Region
from apps.my_plan.services import QUARTER_FIRST_MONTH, get_frontend_context
from apps.schools.models import School

User = get_user_model()

FY = "2027"
#: One school visit in each quarter of FY2027, out of date order on purpose.
VISIT_DATES = (
    date(2027, 4, 9),  # Q3
    date(2026, 10, 6),  # Q1
    date(2027, 7, 2),  # Q4
    date(2027, 1, 14),  # Q2
)


class MyPlanPeriodFilterTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        region = Region.objects.create(name="PF Region")
        district = District.objects.create(name="PF District", region=region)
        cls.user = User.objects.create(
            id="pf-cceo",
            email="pf-cceo@edify.org",
            name="PF Officer",
            roles=["CCEO"],
            active_role="CCEO",
            is_active=True,
        )
        cls.profile = StaffProfile.objects.create(
            id="pf-cceo-sp", user=cls.user, title="CCEO", country="Uganda"
        )
        school = School.objects.create(
            school_id="PF-1",
            name="Pallisa Hill Primary",
            region=region,
            district=district,
            account_owner_id=cls.profile.id,
        )
        for planned in VISIT_DATES:
            Activity.objects.create(
                activity_type="school_visit",
                activity_purpose_text=f"Visit {planned.isoformat()}",
                school=school,
                responsible_staff_id=cls.profile.id,
                delivery_type="staff",
                status="scheduled",
                planned_date=planned,
                fy=FY,
                quarter=get_quarter_for_date(planned),
            )

    def context(self, **query):
        return get_frontend_context(self.user, {"fy": FY, **query})

    def visit_dates(self, ctx):
        return [row["planned_date"] for row in ctx["school_visits"]]

    # --- A year on its own is the whole year -------------------------------

    def test_a_fiscal_year_alone_loads_every_activity_in_it(self):
        ctx = self.context()
        self.assertEqual(ctx["period"], "fy")
        self.assertEqual(len(ctx["school_visits"]), len(VISIT_DATES))

    def test_the_year_is_read_oldest_first(self):
        dates = self.visit_dates(self.context())
        self.assertEqual(dates, sorted(VISIT_DATES))

    def test_nothing_is_selected_in_the_quarter_and_month_selects(self):
        ctx = self.context()
        self.assertIsNone(ctx["selected_quarter"])
        self.assertIsNone(ctx["selected_month"])

    # --- A quarter opens at its first month --------------------------------

    def test_a_quarter_opens_at_its_first_month(self):
        for quarter, month in QUARTER_FIRST_MONTH.items():
            with self.subTest(quarter=quarter):
                ctx = self.context(quarter=quarter)
                self.assertEqual(ctx["period"], "month")
                self.assertEqual(ctx["selected_month"], month)
                self.assertEqual(ctx["selected_quarter"], quarter)

    def test_q1_shows_october_and_only_october(self):
        ctx = self.context(quarter="Q1")
        self.assertEqual(self.visit_dates(ctx), [date(2026, 10, 6)])

    def test_q2_shows_january_not_october(self):
        ctx = self.context(quarter="Q2")
        self.assertEqual(self.visit_dates(ctx), [date(2027, 1, 14)])

    # --- A month is that month ---------------------------------------------

    def test_a_month_loads_that_month(self):
        ctx = self.context(month="4")
        self.assertEqual(ctx["period"], "month")
        self.assertEqual(ctx["selected_month"], 4)
        self.assertEqual(self.visit_dates(ctx), [date(2027, 4, 9)])

    def test_a_month_wins_over_the_quarter_it_sits_in(self):
        """Q3 opens on April, but May was asked for by name."""
        ctx = self.context(quarter="Q3", month="5", quarter_prev="Q3")
        self.assertEqual(ctx["selected_month"], 5)
        self.assertEqual(self.visit_dates(ctx), [])

    # --- Widening clears what it contains ----------------------------------

    def test_changing_the_year_drops_the_quarter_and_month(self):
        ctx = self.context(fy_prev="2026", quarter="Q1", month="10")
        self.assertEqual(ctx["period"], "fy")
        self.assertIsNone(ctx["selected_quarter"])
        self.assertIsNone(ctx["selected_month"])
        self.assertEqual(len(ctx["school_visits"]), len(VISIT_DATES))

    def test_changing_the_quarter_drops_the_month_under_the_old_one(self):
        ctx = self.context(quarter_prev="Q1", quarter="Q3", month="10")
        self.assertEqual(ctx["selected_month"], QUARTER_FIRST_MONTH["Q3"])
        self.assertEqual(self.visit_dates(ctx), [date(2027, 4, 9)])

    def test_the_same_year_resubmitted_keeps_the_month(self):
        ctx = self.context(fy_prev=FY, quarter_prev="Q3", quarter="Q3", month="4")
        self.assertEqual(ctx["selected_month"], 4)

    def test_a_url_without_the_previous_values_is_read_as_written(self):
        """A deep link, the API and the CSV export carry no form state."""
        ctx = self.context(quarter="Q1", month="4")
        self.assertEqual(ctx["selected_month"], 4)

    # --- An explicit period still wins -------------------------------------

    def test_an_explicit_period_overrides_the_derived_one(self):
        ctx = self.context(period="quarter", quarter="Q3")
        self.assertEqual(ctx["period"], "quarter")
        self.assertEqual(self.visit_dates(ctx), [date(2027, 4, 9)])

    def test_only_an_explicit_period_travels_with_the_filter_form(self):
        self.assertEqual(self.context()["period_param"], "")
        self.assertEqual(self.context(month="4")["period_param"], "")
        self.assertEqual(self.context(period="week")["period_param"], "week")

    # --- What the toolbar says ---------------------------------------------

    def test_a_month_counts_as_a_filter_but_not_as_an_advanced_one(self):
        ctx = self.context(month="4")
        self.assertTrue(ctx["filters_active"])
        self.assertFalse(ctx["advanced_filters_active"])

    def test_a_bare_year_is_not_a_filtered_page(self):
        ctx = self.context()
        self.assertFalse(ctx["filters_active"])
        self.assertFalse(ctx["advanced_filters_active"])

    def test_the_form_echoes_what_the_page_was_rendered_with(self):
        ctx = self.context(quarter="Q2")
        self.assertEqual(ctx["fy_prev"], FY)
        self.assertEqual(ctx["quarter_prev"], "Q2")
        self.assertEqual(self.context()["quarter_prev"], "all")

    # --- What the page shows -----------------------------------------------

    def page(self, query=""):
        self.client.force_login(self.user)
        response = self.client.get(f"/my-plan?fy={FY}{query}")
        self.assertEqual(response.status_code, 200)
        return response.content.decode()

    def test_the_toolbar_offers_all_quarters_and_all_months(self):
        """Without them a fiscal year could be chosen but never widened back to."""
        html = self.page()
        self.assertIn("All quarters", html)
        self.assertIn("All months", html)
        self.assertIn('name="fy_prev"', html)
        self.assertIn('name="quarter_prev"', html)

    def test_a_bare_year_does_not_pin_the_form_to_a_period(self):
        self.assertNotIn('name="period"', self.page())

    def test_changing_a_filter_is_what_asks_the_server_for_the_data(self):
        """The trigger belongs on the form, and nowhere else it would be inert.

        `hx-get` is not one of htmx's inherited attributes. Each select carried
        `hx-trigger="change"` with no request of its own to make, so the whole
        toolbar did nothing: a fiscal year could be chosen and the page stayed
        on the one it was already showing. A change event bubbles to the form,
        which is where the request is.
        """
        html = self.page()
        form = html[html.index('id="filters-form"') :]
        form = form[: form.index("</form>")]
        self.assertIn('hx-trigger="change, submit"', form)
        self.assertNotIn('hx-trigger="change"', form)

    def test_the_visits_table_names_the_focus_intervention(self):
        """Owner, 2026-09-17: "Just add focus intervention to the school visit
        table." It was already on the row; only the column was missing."""
        html = self.page()
        card = html[html.index("School Visits Planned") :]
        card = card[: card.index("Trainings Planned")]
        self.assertIn(">Focus Intervention</th>", card)
        self.assertIn('data-label="Intervention"', card)

    def test_the_cards_say_which_period_they_are_showing(self):
        self.assertIn("School Visits Planned for This FY", self.page())
        self.assertIn("School Visits Planned for This Month", self.page("&month=4"))
