"""The drawer reader turns a web drawer into its title, notes and fields."""

from django.test import SimpleTestCase

from apps.mobile_feed import drawer_blocks

EDIT = """
<div data-edify-drawer>
<header class="drawer-header"><h3 id="drawer-title">Edit Feed School</h3>
<p id="drawer-subtitle" class="drawer-header__subtitle">FEED-1 · Mukono</p></header>
<div class="drawer-body">
<p class="drawer-required-note"><span>*</span><span>Required information</span></p>
<form method="post" action="/schools/s1/edit-drawer" hx-post="/schools/s1/edit-drawer">
<input type="hidden" name="csrfmiddlewaretoken" value="t">
<p role="alert" class="edify-note" data-tone="danger">School name is required.</p>
<div class="space-y-1">
<label for="name">School name <span class="text-rose-500">*</span></label>
<input type="text" name="name" id="name" value="Feed School" required maxlength="80">
<p class="edify-text-caption text-slate-500">As the school writes it.</p>
</div>
<div x-data="{ type: 'client', locked: false }">
<div class="space-y-1">
<label for="school_type">Current partner type</label>
<select name="school_type" id="school_type" x-model="type">
<option value="client" selected>Client</option><option value="core">Core</option>
</select>
</div>
<fieldset x-show="type === 'core' || locked" data-cohort-fields>
<legend>Core cohort <span class="text-rose-500" x-show="type === 'core'">*</span></legend>
<div class="space-y-1">
<label for="core_cohort_number">Cohort number</label>
<input type="number" name="core_cohort_number" id="core_cohort_number" value="" min="1" max="99" step="1">
</div>
<p class="edify-text-caption">Set once: after saving, only an Admin can change it.</p>
</fieldset>
</div>
<fieldset>
<legend class="sr-only">Location</legend>
<div class="space-y-1">
<label for="district_id">District <span class="text-rose-500">*</span></label>
<select name="district_id" id="district_id" required hx-get="/schools/sub-counties" hx-target="#sub_county_id">
<option value="">Select a district</option><option value="d1" selected>Mukono (Central Region)</option>
</select>
</div>
<div class="space-y-1">
<label for="sub_county_id">Sub-county</label>
<select name="sub_county_id" id="sub_county_id"><option value="">Select a sub-county</option><option value="sc1" selected>Kasawo</option></select>
</div>
<div class="space-y-1">
<label for="parish_id">Parish</label>
<select name="parish_id" id="parish_id" x-ref="parish">
<option value="">Select a parish</option>
<option value="p1" data-sub-county="sc1">Ddundu</option>
<option value="p2" data-sub-county="sc2">Kiyunga</option>
</select>
</div>
<div class="space-y-1">
<label for="enrollment">Pupil enrolment</label>
<input type="number" name="enrollment" id="enrollment" value="684" min="1">
<p class="edify-text-caption font-semibold text-rose-700">Enter a whole number.</p>
</div>
<div class="space-y-1">
<label for="shipping_address">Shipping address</label>
<textarea name="shipping_address" id="shipping_address">Plot 4</textarea>
</div>
</fieldset>
<div class="drawer-footer">
<button type="button" @click="requestClose()">Cancel</button>
<button type="submit">Save changes</button>
</div>
</form>
</div>
</div>
"""

CLOSE = """
<div data-edify-drawer><header><h3 id="drawer-title">Close Feed School</h3></header>
<div class="drawer-body">
<form hx-post="/schools/FEED-1/close" hx-target="#school-close-result">
<section aria-labelledby="cl-impact"><h3 id="cl-impact">Impact</h3>
<ul><li><span>Active schools</span><span>-1</span></li>
<li><span>Active enrolment <span class="edify-text-caption">(recorded at onboarding)</span></span><span>-684 learners</span></li></ul>
<p class="edify-text-caption">Nothing is deleted.</p></section>
<div class="space-y-1"><label for="closure-type">Closure type <span class="text-rose-500">*</span></label>
<select id="closure-type" name="closure_type" required><option value="">Select a type</option><option value="temporary">Temporarily closed</option></select></div>
<div class="drawer-footer"><button type="submit">Close school</button></div>
</form>
</div></div>
"""

HELD = """
<div data-edify-drawer><header><h3 id="drawer-title">Enter SSA Score</h3>
<p id="drawer-subtitle">Feed School · FY2027</p></header>
<div class="drawer-body">
<div data-ssa-entry-held>
<p class="edify-note" data-tone="info">SSA already entered for FY2027.</p>
<dl><dt>Average score</dt><dd>5.5</dd><dt>Status</dt><dd>Confirmed</dd></dl>
<div class="drawer-footer"><button type="button" @click="requestClose()">Close</button></div>
</div>
</div></div>
"""


class EditDrawerTest(SimpleTestCase):
    def setUp(self):
        self.drawer = drawer_blocks.read(EDIT)
        self.fields = {
            item["field"]["name"]: item["field"]
            for item in self.drawer["items"]
            if "field" in item
        }

    def test_the_drawer_keeps_its_title_and_buttons(self):
        self.assertEqual(self.drawer["title"], "Edit Feed School")
        self.assertEqual(self.drawer["subtitle"], "FEED-1 · Mukono")
        self.assertTrue(self.drawer["hasRequired"])
        self.assertEqual(
            (self.drawer["submitLabel"], self.drawer["cancelLabel"]),
            ("Save changes", "Cancel"),
        )
        self.assertTrue(self.drawer["canSubmit"])

    def test_an_error_note_keeps_its_tone(self):
        self.assertEqual(
            self.drawer["items"][0],
            {"note": {"text": "School name is required.", "tone": "danger"}},
        )

    def test_a_text_field_keeps_label_value_help_and_limits(self):
        name = self.fields["name"]

        self.assertEqual(
            (name["label"], name["kind"], name["value"], name["required"]),
            ("School name", "text", "Feed School", True),
        )
        self.assertEqual(name["help"], "As the school writes it.")
        self.assertEqual(name["maxLength"], 80)

    def test_hidden_inputs_are_not_fields(self):
        self.assertNotIn("csrfmiddlewaretoken", self.fields)

    def test_a_select_keeps_its_choices_and_choice(self):
        district = self.fields["district_id"]

        self.assertEqual(district["kind"], "select")
        self.assertEqual(district["value"], "d1")
        self.assertEqual(
            [o["label"] for o in district["options"]],
            ["Select a district", "Mukono (Central Region)"],
        )

    def test_a_select_that_reloads_another_names_both(self):
        district = self.fields["district_id"]

        self.assertEqual(
            (district["reloadsPath"], district["reloadsTarget"]),
            ("/schools/sub-counties", "sub_county_id"),
        )

    def test_choices_tied_to_another_field_name_it(self):
        parish = self.fields["parish_id"]

        self.assertEqual(parish["groupBy"], "sub_county_id")
        self.assertEqual(
            [(o["value"], o["group"]) for o in parish["options"][1:]],
            [("p1", "sc1"), ("p2", "sc2")],
        )

    def test_a_field_shown_only_for_a_choice_says_which(self):
        cohort = self.fields["core_cohort_number"]

        self.assertEqual(
            cohort["showWhen"], [{"field": "school_type", "values": ["core"]}]
        )
        self.assertEqual((cohort["min"], cohort["max"], cohort["step"]), (1, 99, 1))
        # A field with no condition is always shown.
        self.assertEqual(self.fields["name"].get("showWhen", []), [])

    def test_text_inside_a_conditional_part_shares_its_condition(self):
        line = next(
            item
            for item in self.drawer["items"]
            if item.get("text", "").startswith("Set once")
        )

        self.assertEqual(
            line["showWhen"], [{"field": "school_type", "values": ["core"]}]
        )

    def test_a_field_error_is_kept_with_its_field(self):
        self.assertEqual(self.fields["enrollment"]["error"], "Enter a whole number.")
        self.assertEqual(self.fields["enrollment"]["help"], "")

    def test_a_textarea_keeps_its_text(self):
        address = self.fields["shipping_address"]

        self.assertEqual((address["kind"], address["value"]), ("textarea", "Plot 4"))

    def test_a_visible_legend_is_a_heading_and_a_hidden_one_is_not(self):
        headings = [
            item["heading"] for item in self.drawer["items"] if "heading" in item
        ]

        self.assertEqual(headings, ["Core cohort"])

    def test_the_form_names_the_fields_it_sends(self):
        self.assertEqual(
            drawer_blocks.field_names(EDIT),
            {
                "name",
                "school_type",
                "core_cohort_number",
                "district_id",
                "sub_county_id",
                "parish_id",
                "enrollment",
                "shipping_address",
            },
        )


class CloseAndHeldDrawerTest(SimpleTestCase):
    def test_a_list_of_figures_is_kept_as_lines(self):
        drawer = drawer_blocks.read(CLOSE)
        items = drawer["items"]

        self.assertEqual(items[0], {"heading": "Impact"})
        self.assertEqual(
            items[1]["lines"]["facts"],
            [
                {"label": "Active schools", "value": "-1", "href": ""},
                {
                    "label": "Active enrolment (recorded at onboarding)",
                    "value": "-684 learners",
                    "href": "",
                },
            ],
        )
        self.assertEqual(items[2], {"text": "Nothing is deleted."})
        self.assertEqual(drawer["submitLabel"], "Close school")

    def test_a_drawer_with_nothing_to_save_says_so(self):
        drawer = drawer_blocks.read(HELD)

        self.assertFalse(drawer["canSubmit"])
        self.assertEqual(drawer["cancelLabel"], "Close")
        self.assertEqual(
            drawer["items"][0],
            {"note": {"text": "SSA already entered for FY2027.", "tone": "info"}},
        )
        self.assertEqual(
            drawer["items"][1]["facts"]["facts"],
            [
                {"label": "Average score", "value": "5.5", "href": ""},
                {"label": "Status", "value": "Confirmed", "href": ""},
            ],
        )


class FormDataTest(SimpleTestCase):
    def test_a_save_sends_the_drawers_own_fields_and_hidden_values_only(self):
        drawer = """
        <div data-edify-drawer><div class="drawer-body"><form hx-post="/x">
        <input type="hidden" name="csrfmiddlewaretoken" value="t">
        <input type="hidden" name="school_id" value="FEED-1">
        <div><label for="n">Name</label><input id="n" name="name" value="Old"></div>
        <button type="submit">Save</button></form></div></div>
        """

        data = drawer_blocks.form_data(
            drawer, {"name": "New", "account_owner_id": "someone", "school_id": "x"}
        )

        # The drawer's hidden value stands; a field it does not have is dropped.
        self.assertEqual(data, {"school_id": "FEED-1", "name": "New"})
