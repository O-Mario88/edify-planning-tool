"""The page reader turns the web page's shared components into blocks."""

from django.test import SimpleTestCase

from apps.mobile_feed import page_blocks

HEADER = """
<main>
<a class="edify-back-link" href="/schools"><svg></svg> Back to School Directory</a>
<div class="edify-page-header">
  <div class="edify-page-header__lead">
    <h1 class="edify-page-title">Feed School</h1>
    <p class="edify-page-header__description">School ID: <span>FEED-1</span></p>
  </div>
  <div class="edify-page-header__controls">
    <span class="rounded-pill bg-slate-100 text-slate-500">Readiness: Ready</span>
    <span class="rounded-pill bg-emerald-50 text-emerald-700" title="Source: Recorded">SSA FY2027: 6.0<span class="sr-only"> · Source: Recorded</span></span>
    <button type="button" hx-get="/schools/s1/edit-drawer" class="edify-primary-solid"><svg></svg> Edit Details</button>
    <button type="button" disabled title="SSA already entered for FY2027">Enter SSA Score</button>
  </div>
</div>
<nav data-profile-tabs>
  <a class="is-active" href="/schools/s1?tab=overview&amp;fy=2027" aria-current="page"><span>Overview</span></a>
  <a href="/schools/s1?tab=ssa&amp;fy=2027"><span>SSA</span></a>
</nav>
<p data-profile-scope>Single school, FY 2026/27</p>
<section data-profile-identity><dl>
  <div><dt>School ID</dt><dd>FEED-1</dd></div>
  <div><dt>District</dt><dd><a href="/districts/d1">Mukono</a></dd></div>
</dl></section>
<form class="edify-filter-bar">
  <input type="hidden" name="tab" value="overview">
  <label><span class="edify-filter-label">Fiscal year</span>
    <select name="fy"><option value="2027" selected>FY 2026/27</option><option value="2026">FY 2025/26</option></select>
  </label>
</form>
<section class="context-metrics">
  <header><h2 class="context-metrics__title">Operations</h2></header>
  <div class="context-metrics__sentence">
    <span class="context-metrics__fact" title="learners">
      <a href="/schools/s1?what=enrolment" class="context-metrics__link">
        <span class="context-metrics__label">Enrolment</span>
        <strong class="context-metrics__value" title="872">872</strong>
        <span class="sr-only" data-kpi-note>learners on the school record</span>
      </a>
    </span>
    <span class="context-metrics__fact">
      <span class="context-metrics__text">
        <span class="context-metrics__label">Disbursed</span>
        <strong class="context-metrics__value context-metrics__value--compact"><span class="sr-only">UGX 1,250,000</span><span aria-hidden="true">UGX 1.3M</span></strong>
        <span class="context-metrics__helper" data-tone="danger">of 3 in the plan</span>
      </span>
    </span>
  </div>
  <div class="context-metrics__navigation"><button>Swipe for more</button></div>
</section>
<section class="card"><header class="edify-table-titlebar"><h3>Best Performing And Struggling Intervention</h3><span>FY 2025/26 to FY 2026/27</span></header>
<div><table class="edify-record-table"><caption class="sr-only">The picks.</caption>
<thead><tr><th>Standing</th><th class="text-right">Previous</th></tr></thead>
<tbody><tr>
  <th scope="row"><span class="edify-status-text" data-edify-tone="success">Best performing</span></th>
  <td class="text-right tabular-nums"><a href="/schools/s1?what=intervention"><strong>5.10</strong></a></td>
</tr></tbody></table></div>
<p data-profile-intervention-method>Best performing is the intervention that rose most.</p>
</section>
<aside data-insight-rail>
  <header class="edify-rail__head"><h2>Profile Insights</h2><p>FY 2026/27</p></header>
  <section class="edify-rail__part" data-rail-part="ssa"><h3>SSA Performance</h3>
    <p class="edify-rail__figure"><a href="/schools/s1?tab=ssa">6.00</a> <small>baseline 6.20</small></p>
    <ul class="edify-rail__meters"><li><a href="/x" class="edify-rail__name">Leadership</a><span class="edify-rail__meter"><span style="inline-size: 62%"></span></span><span class="edify-rail__value">6.2</span></li></ul>
    <p class="edify-rail__note">Each intervention out of 10.</p>
  </section>
  <section class="edify-rail__part" data-rail-part="attention"><h3>Needs Attention</h3>
    <ul class="edify-rail__links"><li><a href="/schools/s1?show=unplanned">1 school has nothing planned</a></li></ul>
  </section>
</aside>
</main>
"""


class PageBlocksTest(SimpleTestCase):
    def setUp(self):
        self.page = page_blocks.read(HEADER)

    def test_the_header_keeps_the_page_title_badges_and_actions(self):
        header = self.page["header"]

        self.assertEqual(header["backLabel"], "Back to School Directory")
        self.assertEqual(header["backHref"], "/schools")
        self.assertEqual(header["title"], "Feed School")
        self.assertEqual(header["description"], "School ID: FEED-1")
        self.assertEqual(
            [(b["text"], b["tone"]) for b in header["badges"]],
            [("Readiness: Ready", "plain"), ("SSA FY2027: 6.0", "good")],
        )
        edit, ssa = header["actions"]
        self.assertEqual(
            (edit["label"], edit["primary"], edit["enabled"], edit["href"]),
            ("Edit Details", True, True, "/schools/s1/edit-drawer"),
        )
        self.assertEqual(
            (ssa["label"], ssa["enabled"], ssa["reason"]),
            ("Enter SSA Score", False, "SSA already entered for FY2027"),
        )

    def test_tabs_name_their_key_and_which_is_open(self):
        self.assertEqual(
            [(t["key"], t["label"], t["active"]) for t in self.page["tabs"]],
            [("overview", "Overview", True), ("ssa", "SSA", False)],
        )

    def test_blocks_follow_the_page_in_order(self):
        self.assertEqual(
            [next(iter(block)) for block in self.page["blocks"]],
            ["scopeLine", "facts", "filters", "strip", "table", "rail"],
        )

    def test_facts_keep_their_links(self):
        facts = self.page["blocks"][1]["facts"]["facts"]

        self.assertEqual(
            [(f["label"], f["value"], f["href"]) for f in facts],
            [("School ID", "FEED-1", ""), ("District", "Mukono", "/districts/d1")],
        )

    def test_filters_list_their_options_and_choice(self):
        (fy,) = self.page["blocks"][2]["filters"]["filters"]

        self.assertEqual(
            (fy["name"], fy["label"], fy["value"]), ("fy", "Fiscal year", "2027")
        )
        self.assertEqual(
            [o["label"] for o in fy["options"]], ["FY 2026/27", "FY 2025/26"]
        )

    def test_a_strip_keeps_label_value_helper_note_and_link(self):
        strip = self.page["blocks"][3]["strip"]
        enrolment, disbursed = strip["metrics"]

        self.assertEqual(strip["title"], "Operations")
        self.assertEqual(
            (enrolment["label"], enrolment["value"], enrolment["helper"]),
            ("Enrolment", "872", ""),
        )
        self.assertEqual(enrolment["note"], "learners on the school record")
        self.assertEqual(enrolment["href"], "/schools/s1?what=enrolment")
        # A compact figure shows its short form, as the tile does.
        self.assertEqual(disbursed["value"], "UGX 1.3M")
        self.assertEqual(
            (disbursed["helper"], disbursed["tone"]), ("of 3 in the plan", "danger")
        )
        self.assertEqual(disbursed["href"], "")

    def test_a_table_keeps_columns_cells_tones_and_footnote(self):
        table = self.page["blocks"][4]["table"]

        self.assertEqual(table["title"], "Best Performing And Struggling Intervention")
        self.assertEqual(table["subtitle"], "FY 2025/26 to FY 2026/27")
        self.assertEqual(
            [c["label"] for c in table["columns"]], ["Standing", "Previous"]
        )
        self.assertEqual([c["numeric"] for c in table["columns"]], [False, True])
        first, second = table["rows"][0]["cells"]
        self.assertEqual((first["text"], first["tone"]), ("Best performing", "success"))
        self.assertEqual(
            (second["text"], second["href"], second["strong"]),
            ("5.10", "/schools/s1?what=intervention", True),
        )
        self.assertEqual(
            table["footnote"], "Best performing is the intervention that rose most."
        )

    def test_the_rail_keeps_its_figure_meters_and_links(self):
        rail = self.page["blocks"][5]["rail"]
        ssa, attention = rail["parts"]

        self.assertEqual(
            (rail["title"], rail["subtitle"]), ("Profile Insights", "FY 2026/27")
        )
        self.assertEqual((ssa["figure"], ssa["figureNote"]), ("6.00", "baseline 6.20"))
        self.assertEqual(
            [(m["label"], m["value"], m["fraction"]) for m in ssa["meters"]],
            [("Leadership", "6.2", 0.62)],
        )
        self.assertEqual(ssa["note"], "Each intervention out of 10.")
        self.assertEqual(
            [(link["text"], link["href"]) for link in attention["links"]],
            [("1 school has nothing planned", "/schools/s1?show=unplanned")],
        )

    def test_screen_reader_text_is_not_shown_text(self):
        # "SSA FY2027: 6.0" without its sr-only source line.
        self.assertNotIn("Source", self.page["header"]["badges"][1]["text"])


DETAILS = """
<main>
<section class="card edify-data-chart" aria-label="SSA score by intervention">
  <script type="application/json">{"plotOptions": {"bar": {"horizontal": true}},
   "series": [{"name": "FY 2025/26", "data": [6.7, null]}, {"name": "FY 2026/27", "data": [6.5, 6.0]}],
   "xaxis": {"categories": ["Christlike Behaviour", "Leadership"]},
   "yaxis": {"min": 0, "max": 10, "title": {"text": "SSA score (0-10)"}}}</script>
  <header class="edify-data-chart__header"><h3 class="edify-data-chart__title">SSA score by intervention</h3>
  <p class="edify-data-chart__subtitle">FY 2025/26 and FY 2026/27</p></header>
  <div class="edify-data-chart__plot"></div>
</section>
<div class="edify-surface rounded-surface p-6">
  <h3 class="edify-profile-section-title">School Demographics &amp; Assignment</h3>
  <div class="edify-field-grid">
    <div><p class="edify-profile-field__label">Region</p><p class="edify-profile-field__value">Central Region</p></div>
    <div><p class="edify-profile-field__label">District</p><p class="edify-profile-field__value"><a href="/districts/d1">Mukono</a></p></div>
    <div><p class="edify-profile-field__label">Visit status (FY2027)</p><p class="edify-profile-field__value"><span class="edify-badge" data-tone="neutral">No Visit Planned</span></p></div>
  </div>
  <details><summary class="edify-profile-section-title">Cluster history (1)</summary>
    <ul><li><a href="/clusters/c1">Cluster A</a><span class="block edify-text-caption">10 Nov 2026 – present</span></li></ul>
  </details>
</div>
<section class="edify-surface rounded-surface">
  <header><div><h3>Business Transformation</h3><p class="edify-text-caption">Uganda financial-health journey.</p></div></header>
  <div><section class="edify-section"><h4 class="edify-section__heading">Verified SSA signals</h4>
    <div class="edify-data-list"><div class="edify-data-row"><div><p class="edify-data-row__label">Financial Health</p><p class="edify-data-row__meta">FY2027 · Critical</p></div>
      <span class="edify-data-row__value edify-status-text" data-edify-tone="danger">4.6</span></div></div>
  </section>
  <p class="text-[12px]">No active Business Transformation case is recorded.</p></div>
</section>
<div class="edify-surface rounded-surface p-6">
  <div class="flex"><h3>Data Quality Score</h3><span class="rounded-pill edify-primary-soft">Needs Review</span></div>
  <div data-quality-score><p class="edify-rail__figure"><span>70%</span> <small>of the school's fields complete</small></p>
  <span class="edify-rail__meter"><span style="inline-size: 70%"></span></span>
  <p class="edify-text-caption">Score is updated automatically.</p></div>
</div>
<section class="card p-0"><header class="edify-table-titlebar"><h3>Most Significant Change stories</h3><span>0 records · FY 2026/27</span></header>
  <div class="edify-empty-state"><span class="edify-empty-state__mark"><svg></svg></span><p class="edify-empty-state__message">No record yet: the figure is 0.</p></div>
</section>
<section class="edify-surface rounded-surface" id="acts">
  <header class="edify-table-titlebar"><h3>Planned &amp; Completed Activities</h3><span>0 planned · 0 completed</span></header>
  <div><div data-edify-tablist>
    <button type="button" data-edify-tab class="edify-tab" aria-pressed="true" aria-controls="acts-planned">Planned <span data-edify-tab-count>2</span></button>
    <button type="button" data-edify-tab class="edify-tab" aria-pressed="false" aria-controls="acts-completed">Completed <span data-edify-tab-count>0</span></button>
  </div><p class="edify-text-caption">Visits and trainings at this school.</p></div>
  <div id="acts-planned"><table class="edify-record-table"><thead><tr><th>Date</th></tr></thead><tbody><tr><td>10 Nov 2026</td></tr></tbody></table></div>
  <div id="acts-completed"><div class="edify-empty-state"><p class="edify-empty-state__message">Nothing completed yet.</p></div></div>
</section>
</main>
"""


class PageBlocksDetailsTest(SimpleTestCase):
    def setUp(self):
        self.blocks = page_blocks.read(DETAILS)["blocks"]

    def test_blocks_follow_the_page_in_order(self):
        self.assertEqual(
            [next(iter(block)) for block in self.blocks],
            ["chart", "panel", "panel", "panel", "table", "segments"],
        )

    def test_a_chart_carries_the_data_the_page_charts(self):
        chart = self.blocks[0]["chart"]

        self.assertEqual(
            (chart["title"], chart["subtitle"], chart["horizontal"]),
            ("SSA score by intervention", "FY 2025/26 and FY 2026/27", True),
        )
        self.assertEqual(chart["categories"], ["Christlike Behaviour", "Leadership"])
        self.assertEqual(
            [(s["name"], s["values"]) for s in chart["series"]],
            # A reading with no score draws no bar.
            [("FY 2025/26", [6.7, 0.0]), ("FY 2026/27", [6.5, 6.0])],
        )
        self.assertEqual(
            (chart["min"], chart["max"], chart["axisTitle"]),
            (0, 10, "SSA score (0-10)"),
        )

    def test_a_panel_keeps_its_fields_and_history(self):
        panel = self.blocks[1]["panel"]

        self.assertEqual(panel["title"], "School Demographics & Assignment")
        fields, heading, links = panel["items"]
        self.assertEqual(
            [(f["label"], f["value"], f["href"]) for f in fields["fields"]["facts"]],
            [
                ("Region", "Central Region", ""),
                ("District", "Mukono", "/districts/d1"),
                ("Visit status (FY2027)", "No Visit Planned", ""),
            ],
        )
        self.assertEqual(heading, {"heading": "Cluster history (1)"})
        self.assertEqual(
            links["links"]["links"],
            [
                {
                    "text": "Cluster A",
                    "href": "/clusters/c1",
                    "caption": "10 Nov 2026 – present",
                }
            ],
        )

    def test_a_panel_keeps_its_subtitle_rows_and_text(self):
        panel = self.blocks[2]["panel"]

        self.assertEqual(
            (panel["title"], panel["subtitle"]),
            ("Business Transformation", "Uganda financial-health journey."),
        )
        heading, rows, text = panel["items"]
        self.assertEqual(heading, {"heading": "Verified SSA signals"})
        self.assertEqual(
            rows["rows"]["rows"],
            [
                {
                    "label": "Financial Health",
                    "meta": "FY2027 · Critical",
                    "value": "4.6",
                    "tone": "danger",
                }
            ],
        )
        self.assertEqual(
            text["text"], "No active Business Transformation case is recorded."
        )

    def test_a_panel_keeps_its_badge_and_meter(self):
        panel = self.blocks[3]["panel"]

        self.assertEqual([b["text"] for b in panel["badges"]], ["Needs Review"])
        meter, caption = panel["items"]
        self.assertEqual(
            meter["meter"],
            {
                "label": "of the school's fields complete",
                "value": "70%",
                "fraction": 0.7,
                "href": "",
            },
        )
        self.assertEqual(caption["text"], "Score is updated automatically.")

    def test_an_empty_table_card_says_why(self):
        table = self.blocks[4]["table"]

        self.assertEqual(table["title"], "Most Significant Change stories")
        self.assertEqual(table["rows"], [])
        self.assertEqual(table["emptyMessage"], "No record yet: the figure is 0.")

    def test_segments_carry_each_part_of_the_switch(self):
        segments = self.blocks[5]["segments"]

        self.assertEqual(
            (segments["title"], segments["subtitle"], segments["caption"]),
            (
                "Planned & Completed Activities",
                "0 planned · 0 completed",
                "Visits and trainings at this school.",
            ),
        )
        planned, completed = segments["segments"]
        self.assertEqual(
            (planned["label"], planned["count"], planned["active"]),
            ("Planned", "2", True),
        )
        self.assertEqual(next(iter(planned["blocks"][0])), "table")
        self.assertEqual(completed["blocks"], [{"empty": "Nothing completed yet."}])


MY_PLAN = """
<main>
<div class="edify-view-toolbar">
  <nav data-edify-tablist data-edify-beside-link aria-label="My plan horizon">
    <a href="?period=week" data-edify-tab class="edify-tab">This Week</a>
    <a href="?period=fy" data-edify-tab class="edify-tab" aria-current="page">This FY</a>
  </nav>
  <a href="/calendar" class="btn btn-primary" aria-label="Open Calendar"><span>Open Calendar</span></a>
  <form data-component="filter-toolbar" class="edify-surface rounded-surface">
    <input type="hidden" name="fy_prev" value="2027">
    <div><span class="edify-filter-label">Fiscal year</span>
    <select name="fy"><option value="2026">FY 2026</option><option value="2027" selected>FY 2027</option></select></div>
  </form>
</div>
<div class="card overflow-hidden">
  <div class="px-5 py-4 flex">
    <div class="flex"><span><svg></svg></span><h2>School Visits Planned for This FY</h2></div>
    <div class="flex"><span class="px-2 rounded-pill">1</span></div>
  </div>
  <div class="overflow-x-auto">
  <table class="edify-data-table">
    <thead><tr><th class="school-plan-table__select"><input type="checkbox"></th><th>School ID</th><th>Status</th><th class="text-right">Actions</th></tr></thead>
    <tbody>
      <tr data-overdue>
        <td class="school-plan-table__select"><label><input type="checkbox" value="a1" aria-label="Select School Visit at Feed School"></label></td>
        <td>FEED-1</td>
        <td><span class="mp-badge mp-badge--amber">Missing Salesforce ID</span></td>
        <td data-record-action>
          <button type="button" hx-get="/my-plan/a1/complete-drawer" class="btn">Complete</button>
          <div class="row-menu"><button class="row-menu__trigger">Actions</button>
            <div class="row-menu__list" role="menu">
              <button hx-get="/my-plan/a1" class="row-menu__item" role="menuitem">View Details</button>
              <button hx-get="/my-plan/a1/cancel-drawer" class="row-menu__item row-menu__item--danger" role="menuitem">Cancel Activity</button>
            </div></div>
        </td>
      </tr>
    </tbody>
  </table>
  <nav class="edify-pagination" aria-label="School visit pages">
    <p class="edify-pagination__summary">Showing 1–50 of 51</p>
    <span aria-current="page" class="edify-pagination__control edify-pagination__control--current">1</span>
    <a href="?school_visits_page=2" class="edify-pagination__control">2</a>
    <a href="?school_visits_page=2" rel="next" aria-label="Next page" class="edify-pagination__control edify-pagination__control--direction">Next</a>
  </nav>
  </div>
</div>
<div class="card overflow-hidden">
  <div class="px-5 py-4 flex"><div class="flex"><h2>Cluster Planning Status</h2></div>
    <div class="flex">
<span>15 clusters</span>
<span aria-hidden="true">·</span>
<span>3 without a meeting</span>
</div></div>
  <div class="px-5 py-4"><div class="edify-empty-state edify-empty-state--line"><p class="edify-empty-state__message">No clusters.</p>
    <a href="/planning" class="underline">Open Planning <span aria-hidden="true">→</span></a></div></div>
</div>
<div class="card p-5">
  <div class="mb-4"><h3>Plan Breakdown by Period</h3><p>All activity types combined</p></div>
  <div class="grid grid-cols-2">
    <div class="flex"><div><svg></svg></div><div><p class="uppercase">This Week</p><p>3 <span>activities</span></p></div></div>
    <div class="flex"><div><svg></svg></div><div><p class="uppercase">This FY</p><p>9 <span>activities</span></p></div></div>
  </div>
</div>
<div hx-get="/my-plan/readiness?fy=2027" hx-trigger="load"><p>Working out…</p></div>
</main>
"""


class MyPlanComponentsTest(SimpleTestCase):
    def setUp(self):
        self.later = []

        def later(path):
            self.later.append(path)
            return '<div class="card"><h2>Readiness</h2><div class="edify-empty-state"><p>None yet.</p></div></div>'

        self.blocks = page_blocks.read(MY_PLAN, later)["blocks"]

    def kind(self, name):
        return [b[name] for b in self.blocks if name in b]

    def test_link_tabs_carry_the_link_beside_them(self):
        tabs = self.kind("linkTabs")[0]

        self.assertEqual(
            [(t["label"], t["active"]) for t in tabs["tabs"]],
            [("This Week", False), ("This FY", True)],
        )
        self.assertEqual(
            (tabs["beside"]["label"], tabs["beside"]["href"]),
            ("Open Calendar", "/calendar"),
        )

    def test_the_filter_toolbar_keeps_its_hidden_values(self):
        filters = self.kind("filters")[0]

        self.assertEqual(filters["filters"][0]["value"], "2027")
        self.assertEqual(filters["hidden"], {"fy_prev": "2027"})

    def test_a_plain_card_table_has_its_title_count_ticks_badges_menu_and_pager(self):
        table = self.kind("table")[0]

        self.assertEqual(
            (table["title"], table["count"]), ("School Visits Planned for This FY", "1")
        )
        self.assertEqual(
            [c["label"] for c in table["columns"]], ["School ID", "Status", "Actions"]
        )
        row = table["rows"][0]
        self.assertEqual((row["tone"], row["pickId"]), ("overdue", "a1"))
        self.assertEqual(
            (row["cells"][1]["tone"], row["cells"][1]["badge"]), ("amber", True)
        )
        actions = row["cells"][2]["actions"]
        self.assertEqual(
            [(a["label"], a["key"], a["primary"]) for a in actions],
            [
                ("Complete", "button", True),
                ("View Details", "menu", False),
                ("Cancel Activity", "danger", False),
            ],
        )
        self.assertEqual(table["pager"]["summary"], "Showing 1–50 of 51")
        self.assertEqual(
            [p["label"] for p in table["pager"]["pages"]], ["1", "2", "Next"]
        )

    def test_a_cards_summary_line_and_its_empty_states_way_out(self):
        table = self.kind("table")[1]

        self.assertEqual(table["subtitle"], "15 clusters · 3 without a meeting")
        self.assertEqual(
            (table["emptyAction"]["label"], table["emptyAction"]["href"]),
            ("Open Planning", "/planning"),
        )

    def test_a_card_of_tiles_is_a_strip(self):
        strip = self.kind("strip")[0]

        self.assertEqual(strip["subtitle"], "All activity types combined")
        self.assertEqual(
            [(m["label"], m["value"]) for m in strip["metrics"]],
            [("This Week", "3 activities"), ("This FY", "9 activities")],
        )

    def test_a_part_loaded_later_is_read_in_its_place(self):
        self.assertEqual(self.later, ["/my-plan/readiness?fy=2027"])
        self.assertEqual(self.kind("table")[-1]["title"], "Readiness")


TODOS = """
<main>
<div x-data="{ cat: 'all', prio: 'all' }">
  <header class="mobile-role-home edify-page-header" data-mobile-role-home>
    <div class="mobile-role-home__copy"><p>My work</p><h1 class="edify-page-title">Action queue</h1><span>Start with the highest-priority task.</span></div>
    <div class="mobile-role-home__context"><span class="mobile-role-home__figure"><strong>45</strong> open</span></div>
    <a href="/my-plan/a1" class="mobile-role-home__action" data-mobile-primary-action><span>Do next: Chase Partner Delivery</span><span aria-hidden="true">→</span></a>
  </header>
  <section class="mobile-home-only mobile-home-section">
    <div class="mobile-home-section__header"><h2>Do next</h2><span>45 open</span></div>
    <div class="card px-3 divide-y divide-slate-50">
      <div class="flex items-center"><div class="h-8 w-8 bg-amber-50"><svg></svg></div>
        <div class="min-w-0 flex-1"><p>Enter SSA</p><p>Feed School</p></div>
        <span class="hidden sm:inline-flex rounded-pill bg-rose-50">Critical</span>
        <a href="/schools/s1/ssa-entry">Open</a></div>
    </div>
  </section>
  <div class="edify-page-header mobile-home-hide"><h1 class="edify-page-title">To-Do</h1></div>
  <div data-edify-tablist role="group" aria-label="Category">
    <button type="button" data-edify-tab class="edify-tab" @click="cat='all'">All Categories</button>
    <button type="button" data-edify-tab class="edify-tab" @click="cat='Finance'">Finance <span data-edify-tab-count>4</span></button>
  </div>
  <div class="card px-4 divide-y divide-slate-50">
    <details class="todo-group" x-show="(cat === 'all' || cat === 'Finance') &amp;&amp; (prio === 'all' || prio === 'high')">
      <summary><span class="min-w-0 flex-1"><span class="block">Confirm Fund Request</span><span class="block">2 · Apr 20, Apr 13</span></span><span class="todo-group__count">2</span></summary>
      <div class="todo-group__rows divide-y">
        <div class="flex"><div class="min-w-0 flex-1"><p>Confirm Fund Request</p><p>Apr 20</p></div><a href="/fund-requests/1">Open</a></div>
        <div class="flex"><div class="min-w-0 flex-1"><p>Confirm Fund Request</p><p>Apr 13</p></div><a href="/fund-requests/2">Open</a></div>
      </div>
    </details>
  </div>
  <div class="rounded-surface"><p>Showing every task.</p><a href="/todos/history">History</a></div>
</div>
</main>
"""


class PhoneComponentsTest(SimpleTestCase):
    def setUp(self):
        self.page = page_blocks.read(TODOS)
        self.blocks = self.page["blocks"]

    def test_the_phones_role_home_is_the_header(self):
        header = self.page["header"]

        self.assertEqual(
            (header["eyebrow"], header["title"]), ("My work", "Action queue")
        )
        self.assertEqual(header["badges"][0]["text"], "45 open")
        self.assertEqual(
            header["actions"][0]["label"], "Do next: Chase Partner Delivery"
        )

    def test_what_a_phone_does_not_draw_is_left_out(self):
        text = repr(self.blocks)

        self.assertNotIn("To-Do", text)
        self.assertNotIn("Critical", text)

    def test_a_home_section_is_a_titled_list_of_rows(self):
        section = self.blocks[0]["list"]

        self.assertEqual((section["title"], section["count"]), ("Do next", "45 open"))
        item = section["items"][0]
        self.assertEqual(
            (item["title"], item["lines"], item["tone"]),
            ("Enter SSA", ["Feed School"], "caution"),
        )
        self.assertEqual(item["actions"][0]["href"], "/schools/s1/ssa-entry")

    def test_chips_carry_their_values_counts_and_opening_choice(self):
        chips = self.blocks[1]["chips"]

        self.assertEqual((chips["name"], chips["value"]), ("cat", "all"))
        self.assertEqual(
            [(c["value"], c["count"]) for c in chips["chips"]],
            [("all", ""), ("Finance", "4")],
        )

    def test_a_group_opens_onto_its_rows_and_keeps_its_filter_keys(self):
        group = self.blocks[2]["list"]["items"][0]

        self.assertEqual(
            (group["title"], group["count"]), ("Confirm Fund Request", "2")
        )
        self.assertEqual(
            [c["lines"] for c in group["children"]], [["Apr 20"], ["Apr 13"]]
        )
        self.assertEqual(group["keys"], {"cat": "Finance", "prio": "high"})

    def test_a_section_no_reader_knows_is_a_plain_panel(self):
        panel = self.blocks[3]["panel"]

        self.assertEqual(panel["items"][0], {"text": "Showing every task."})
        self.assertEqual(
            panel["items"][1]["links"]["links"][0]["href"], "/todos/history"
        )


class BesideLinkTest(SimpleTestCase):
    def test_the_link_beside_link_tabs_is_read_once(self):
        blocks = page_blocks.read(MY_PLAN)["blocks"]

        self.assertFalse(
            any("panel" in b and "Open Calendar" in repr(b) for b in blocks), blocks[:3]
        )


CLUSTER_CARDS = """
<main><div class="space-y-3">
<div class="cluster-card edify-surface rounded-surface" x-data="{ cardExpanded: false }">
 <div class="cluster-card__summary" data-row-disclosure-summary>
  <div class="cluster-card__header-row">
   <div class="cluster-card__title-row">
    <h3 class="cluster-card__title" data-list-title>
     <button type="button" class="cluster-card__name-toggle">Cluster A</button></h3>
    <span class="edify-status-badge danger">Critical</span>
   </div>
   <div class="cluster-card__actions"><div class="row-menu">
    <button type="button" class="row-menu__trigger">Actions</button>
    <div class="row-menu__panel" role="menu">
     <button type="button" class="row-menu__item" role="menuitem"
      hx-get="/planning/schedule-modal?cluster_id=c1&action=training"
      hx-target="#drawer-container">Schedule Group Training</button>
     <button type="button" class="row-menu__item" role="menuitem"
      hx-get="/clusters/c1/bulk-assign-drawer" hx-target="#drawer-container">Add Schools</button>
    </div></div></div>
  </div>
  <dl class="school-record-row__metadata cluster-card__metadata">
   <div><dt>Location:</dt><dd>Mukono, Goma</dd></div>
   <div><dt>Schools:</dt><dd>7</dd></div>
   <div class="school-record-row__ssa is-danger"><dt>Avg SSA:</dt><dd>4.6/10</dd></div>
   <div class="cluster-card__metadata-warning"><dt>Without SSA:</dt><dd>2 schools</dd></div>
   <div><dt>Owner:</dt><dd><a href="/staff/p1">Paul N.</a></dd></div>
  </dl>
 </div>
 <div id="cluster-details-c1" x-show="cardExpanded" x-cloak class="cluster-card__details">
  <a href="/clusters/c1" class="edify-text-caption">Open Cluster A cluster profile</a>
  <div class="edify-surface rounded-surface" x-ref="schoolsContainer"
   hx-get="/partials/clusters/c1/schools" hx-trigger="load-schools, cluster-schools-updated-c1 from:body">
   <div>Loading schools list...</div>
  </div>
 </div>
</div>
</div></main>
"""


class RecordCardTest(SimpleTestCase):
    def test_a_record_card_is_one_block_with_its_parts(self):
        blocks = page_blocks.read(CLUSTER_CARDS)["blocks"]

        self.assertEqual(len(blocks), 1, blocks)
        record = blocks[0]["record"]
        self.assertEqual(record["title"], "Cluster A")
        self.assertEqual(
            record["badges"], [{"text": "Critical", "tone": "alert", "title": ""}]
        )
        self.assertEqual(
            [(a["label"], a["drawer"]) for a in record["actions"]],
            [("Schedule Group Training", True), ("Add Schools", True)],
        )
        self.assertEqual(
            [(f["label"], f["value"], f["tone"], f["href"]) for f in record["facts"]],
            [
                ("Location", "Mukono, Goma", "", ""),
                ("Schools", "7", "", ""),
                ("Avg SSA", "4.6/10", "alert", ""),
                ("Without SSA", "2 schools", "caution", ""),
                ("Owner", "Paul N.", "", "/staff/p1"),
            ],
        )

    def test_what_opening_the_card_shows_is_read_with_it(self):
        record = page_blocks.read(CLUSTER_CARDS)["blocks"][0]["record"]

        # The profile link is the card's own; the schools list loads on opening.
        self.assertEqual(record["href"], "/clusters/c1")
        self.assertEqual(record["detailsPath"], "/partials/clusters/c1/schools")
        self.assertFalse(any("Loading schools" in repr(b) for b in record["details"]))


ROWS_WITH_DETAILS = """
<main><table class="school-plan-table" x-data="{ openSchoolId: null }">
<thead><tr><th>School ID</th><th>School Name</th></tr></thead>
<tbody>
<tr class="cluster-school-row"><td>1546</td><td>Central Primary</td></tr>
<tr id="d-1" class="school-plan-table__details" x-show="openSchoolId === 's1'" x-cloak>
 <td colspan="2"><a href="/schools/s1">Open Central Primary school profile</a>
 <dl class="school-record-row__metadata">
  <div><dt>District:</dt><dd>Mukono</dd></div>
  <div><dt>Last Visit:</dt><dd class="edify-status-text" data-edify-tone="danger">Never</dd></div>
 </dl></td></tr>
<tr class="cluster-school-row"><td>1598</td><td>Goma Primary</td></tr>
</tbody></table></main>
"""


class RowDetailsTest(SimpleTestCase):
    def test_a_rows_hidden_details_open_under_it_not_as_a_row(self):
        table = page_blocks.read(ROWS_WITH_DETAILS)["blocks"][0]["table"]

        self.assertEqual(
            [r["cells"][0]["text"] for r in table["rows"]], ["1546", "1598"]
        )
        first = table["rows"][0]
        self.assertEqual(first["detailsHref"], "/schools/s1")
        self.assertEqual(
            [(f["label"], f["value"], f["tone"]) for f in first["details"]],
            [("District", "Mukono", ""), ("Last Visit", "Never", "alert")],
        )
        self.assertNotIn("details", table["rows"][1])


SELECTION_BAR = """
<main><div x-data="{ selectedSchools: [] }">
<div class="school-directory-listbar" x-cloak x-show="selectedSchools.length > 0">
 <span x-text="selectedSchools.length"></span> schools selected
 <button type="button" @click="selectedSchools = []">Clear</button>
</div>
<p>Click a school to see its scores.</p>
<div x-show="selectedSchools.length > 0 && activeView === 'list'" style="display: none;">
 <span>schools selected</span></div>
</div></main>
"""


class HiddenOnOpeningTest(SimpleTestCase):
    def test_a_bar_shown_only_once_something_is_ticked_is_not_drawn(self):
        blocks = page_blocks.read(SELECTION_BAR)["blocks"]

        self.assertNotIn("Clear", repr(blocks))
        self.assertNotIn("schools selected", repr(blocks))
        self.assertIn("Click a school", repr(blocks))


SCOPED_PAGER = """
<main><div class="edify-pagination-scope flex">
<span>Showing 1 to 5 of 15 clusters</span>
<div class="flex">
<span aria-current="page" class="h-8 w-8">1</span>
<button hx-get="/clusters?page=2" hx-include="#filters-form">2</button>
<span aria-hidden="true">…</span>
<button aria-label="Next page" hx-get="/clusters?page=2"><svg></svg></button>
</div></div></main>
"""


class ScopedPagerTest(SimpleTestCase):
    def test_a_pager_outside_a_table_card_is_a_pager(self):
        blocks = page_blocks.read(SCOPED_PAGER)["blocks"]

        self.assertEqual(
            blocks,
            [
                {
                    "pager": {
                        "summary": "Showing 1 to 5 of 15 clusters",
                        "pages": [
                            {"label": "1", "href": "", "current": True},
                            {
                                "label": "2",
                                "href": "/clusters?page=2",
                                "current": False,
                            },
                            {"label": "…", "href": "", "current": False},
                            {
                                "label": "Next",
                                "href": "/clusters?page=2",
                                "current": False,
                            },
                        ],
                    }
                }
            ],
        )


INLINE_FORM = """
<main>
<div class="edify-surface rounded-surface border p-5">
<h2>Escalate to your Programme Lead</h2>
<p>Use this when something is blocking your schools.</p>
<form method="POST" class="grid">
<input type="hidden" name="csrfmiddlewaretoken" value="t">
<input type="hidden" name="action" value="raise">
<div><label for="c">Category</label>
<select id="c" name="category" required><option value="funding">Funding gap</option></select></div>
<div><label for="s">Subject</label><input id="s" type="text" name="subject" required maxlength="255"></div>
<div><label for="d">What is happening</label><textarea id="d" name="detail" required></textarea></div>
<div><button type="submit" class="btn btn-primary">Send to Programme Lead</button></div>
</form>
</div>
</main>
"""


class PageFormTest(SimpleTestCase):
    def test_a_form_the_page_shows_itself_is_a_form_block(self):
        blocks = page_blocks.read(INLINE_FORM)["blocks"]

        self.assertEqual(len(blocks), 1, blocks)
        form = blocks[0]["form"]
        self.assertEqual(form["title"], "Escalate to your Programme Lead")
        self.assertEqual(
            form["text"], "Use this when something is blocking your schools."
        )
        self.assertEqual(form["key"], "raise")
        self.assertEqual(form["submitLabel"], "Send to Programme Lead")
        fields = [item["field"] for item in form["items"] if "field" in item]
        self.assertEqual(
            [(f["name"], f["kind"], f["required"]) for f in fields],
            [
                ("category", "select", True),
                ("subject", "text", True),
                ("detail", "textarea", True),
            ],
        )


PAGE_DIALOG = """
<main><div x-data="{ showRollup: false, showMscs: false }">
<div class="edify-page-header"><h1>My Targets</h1>
<div class="edify-page-header__controls">
<button type="button" @click="showMscs = true" class="h-8 px-3">Submit MSCS</button>
</div></div>
<p>Track your targets.</p>
<div x-show="showMscs" x-cloak role="dialog" aria-modal="true">
 <div class="edify-surface rounded-surface p-5">
  <div><h3>Submit MSCS</h3><p>Counts toward your MSCS target once approved.</p>
  <button type="button" aria-label="Close MSCS form" @click="showMscs = false">x</button></div>
  <form method="post" action="/my-targets/mscs">
   <div><label for="t">Title</label><input id="t" name="title" required></div>
   <button type="submit">Submit</button>
  </form>
 </div>
</div>
</div></main>
"""


class PageDialogTest(SimpleTestCase):
    def test_a_button_that_opens_a_dialog_opens_it_natively(self):
        page = page_blocks.read(PAGE_DIALOG)

        submit = next(
            a for a in page["header"]["actions"] if a["label"] == "Submit MSCS"
        )
        self.assertEqual((submit["href"], submit["drawer"]), ("#dialog=showMscs", True))
        # The closed dialog is not drawn on the page itself.
        self.assertNotIn("form", repr(page["blocks"]))
        self.assertEqual([d["key"] for d in page["dialogs"]], ["showMscs"])
        dialog = page["dialogs"][0]
        self.assertEqual(dialog["title"], "Submit MSCS")
        form = dialog["blocks"][0]["form"]
        # The sheet carries the title; the form under it does not repeat it.
        self.assertEqual((form["title"], form["submitLabel"]), ("", "Submit"))
