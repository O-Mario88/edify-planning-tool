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


SCRIPTED_CHECKLIST = """
<div data-edify-drawer><div class="drawer-body">
<div x-data='{
  selectedDistrictId: "",
  subCounties: [{"id": "s1", "name": "Goma", "district_id": "d1"},
                {"id": "s2", "name": "Nama", "district_id": "d1", "covered_by": "Goma Cluster"},
                {"id": "s3", "name": "Kira", "district_id": "d2"}],
  selectedSubCounties: ["s2"],
  get visibleSubCounties() {
    return this.subCounties.filter(sc => String(sc.district_id) === String(this.selectedDistrictId));
  }
}'>
<form action="/clusters/create" method="post">
<div><label for="d">District <span aria-hidden="true">*</span></label>
<select id="d" name="district_id" x-model="selectedDistrictId" required>
<option value="">Select a district</option><option value="d1">Mukono</option>
<option value="d2">Wakiso</option></select></div>
<fieldset aria-required="true">
<legend>Sub-counties <span aria-hidden="true">*</span>
<span>(<span x-text="selectedSubCounties.length">0</span> selected)</span></legend>
<label data-select-all-label><input type="checkbox" data-select-all="x"><span>Select all</span></label>
<div>
<template x-for="subCounty in visibleSubCounties" :key="subCounty.id">
<label><input type="checkbox" name="sub_county_ids" :value="subCounty.id"
 x-model="selectedSubCounties"><span><span x-text="subCounty.name"></span><span x-show="subCounty.covered_by" x-text="`Also in ${subCounty.covered_by}`"></span></span></label>
</template>
<div x-show="!selectedDistrictId"><span>Choose a district to see its sub-counties.</span></div>
</div>
<p x-show="subCountyError" role="alert">Select at least one sub-county for this cluster.</p>
</fieldset>
<button type="submit">Create cluster</button>
</form></div></div></div>
"""

RENDERED_CHECKLIST = """
<div data-edify-drawer><div class="drawer-body"><form hx-post="/x">
<fieldset>
<legend>Schools in this cluster (<span x-text="kept">2</span> of 2 kept)</legend>
<p>Untick a school added by mistake.</p>
<label data-select-all-label><input type="checkbox" data-select-all><span>Select all</span></label>
<div role="group">
<label><input type="checkbox" name="member_school_ids" value="a" checked>
<span><span class="block">Alpha Primary</span><span class="block">SCH-1</span></span></label>
<label><input type="checkbox" name="member_school_ids" value="b">
<span><span class="block">Beta Primary</span><span class="block">SCH-2</span></span></label>
</div></fieldset>
<button type="submit">Save</button></form></div></div>
"""


class ChecklistTest(SimpleTestCase):
    def _fields(self, html):
        return [
            item["field"]
            for item in drawer_blocks.read(html)["items"]
            if "field" in item
        ]

    def test_boxes_a_script_draws_are_one_field_with_the_scripts_choices(self):
        fields = self._fields(SCRIPTED_CHECKLIST)

        checklist = next(f for f in fields if f["name"] == "sub_county_ids")
        self.assertEqual(checklist["kind"], "checklist")
        self.assertEqual(checklist["label"], "Sub-counties")
        self.assertTrue(checklist["required"])
        self.assertEqual(checklist["value"], "s2")
        self.assertEqual(checklist["groupBy"], "district_id")
        self.assertEqual(
            [(o["value"], o["label"], o["group"]) for o in checklist["options"]],
            [("s1", "Goma", "d1"), ("s2", "Nama", "d1"), ("s3", "Kira", "d2")],
        )
        # The line the script prints under a sub-county another cluster covers.
        self.assertEqual(
            [o["detail"] for o in checklist["options"]],
            ["", "Also in Goma Cluster", ""],
        )
        # The Select all box is the checklist's own, not a field of its own.
        self.assertEqual([f["name"] for f in fields], ["district_id", "sub_county_ids"])

    def test_boxes_the_web_drew_are_one_field_with_their_ticks(self):
        items = drawer_blocks.read(RENDERED_CHECKLIST)["items"]

        checklist = items[0]["field"]
        self.assertEqual(checklist["kind"], "checklist")
        self.assertEqual(checklist["label"], "Schools in this cluster")
        self.assertEqual(checklist["help"], "Untick a school added by mistake.")
        self.assertEqual(checklist["value"], "a")
        self.assertEqual(
            [(o["value"], o["label"], o["detail"]) for o in checklist["options"]],
            [("a", "Alpha Primary", "SCH-1"), ("b", "Beta Primary", "SCH-2")],
        )
        self.assertEqual(len(items), 1)

    def test_a_save_sends_each_ticked_box(self):
        data = drawer_blocks.form_data(
            SCRIPTED_CHECKLIST, {"district_id": "d1", "sub_county_ids": "s1,s2"}
        )

        self.assertEqual(data, {"district_id": "d1", "sub_county_ids": ["s1", "s2"]})

    def test_a_save_with_nothing_ticked_sends_no_box(self):
        data = drawer_blocks.form_data(RENDERED_CHECKLIST, {"member_school_ids": ""})

        self.assertEqual(data, {"member_school_ids": []})


COMMA_CHECKLIST = """
<div data-edify-drawer><div class="drawer-body">
<form method="post" action="/pl/review-queue/a1/return">
<fieldset><legend>Why are you returning it?</legend>
<label><input type="checkbox" name="reasons" value="Participants missing"> Participants missing</label>
<label><input type="checkbox" name="reasons" value="Wrong school, cluster or date" checked> Wrong school, cluster or date</label>
</fieldset>
</form></div></div>
"""


class CommaInATickBoxTest(SimpleTestCase):
    """A checklist travels as its ticks joined by commas, so a box whose own
    value holds one would come back as two boxes that do not exist."""

    def test_a_box_is_offered_without_its_commas(self):
        items = drawer_blocks.read(COMMA_CHECKLIST)["items"]
        fields = [item["field"] for item in items if "field" in item]
        reasons = next(f for f in fields if f["name"] == "reasons")

        self.assertEqual(
            [(o["value"], o["label"]) for o in reasons["options"]],
            [
                ("Participants missing", "Participants missing"),
                ("Wrong school cluster or date", "Wrong school, cluster or date"),
            ],
        )
        self.assertEqual(reasons["value"], "Wrong school cluster or date")

    def test_a_save_sends_the_box_as_the_web_writes_it(self):
        data = drawer_blocks.form_data(
            COMMA_CHECKLIST,
            {"reasons": "Participants missing,Wrong school cluster or date"},
        )

        self.assertEqual(
            data,
            {"reasons": ["Participants missing", "Wrong school, cluster or date"]},
        )


class BoundValueTest(SimpleTestCase):
    def test_a_field_bound_to_the_drawers_data_opens_with_its_value(self):
        drawer = """
        <div data-edify-drawer><div class="drawer-body">
        <div x-data='{ clusterName: "Cluster A", teachers: 3, open: true }'>
        <form hx-post="/x">
        <div><label for="n">Cluster name</label>
        <input id="n" name="name" x-model="clusterName"></div>
        <div><label for="t">Teachers</label>
        <input id="t" type="number" name="teachers" x-model.number="teachers"></div>
        <div><label for="o">Typed</label>
        <input id="o" name="typed" value="kept" x-model="clusterName"></div>
        </form></div></div></div>
        """

        fields = [i["field"] for i in drawer_blocks.read(drawer)["items"]]

        self.assertEqual(
            [(f["name"], f["value"]) for f in fields],
            [("name", "Cluster A"), ("teachers", "3"), ("typed", "kept")],
        )


class RepeatedHiddenValuesTest(SimpleTestCase):
    def test_every_hidden_value_of_a_repeated_name_is_sent(self):
        drawer = """
        <div data-edify-drawer><div class="drawer-body"><form hx-post="/activity-selection/cancel">
        <input type="hidden" name="activity_ids" value="a1">
        <input type="hidden" name="activity_ids" value="a2">
        <div><label for="r">Reason</label><textarea id="r" name="reason"></textarea></div>
        <button type="submit">Cancel them</button></form></div></div>
        """

        data = drawer_blocks.form_data(drawer, {"reason": "Exams", "activity_ids": "x"})

        self.assertEqual(data, {"reason": "Exams", "activity_ids": ["a1", "a2"]})


RADIO_DRAWER = """
<div data-edify-drawer><div class="drawer-body"><form hx-post="/exports/prepare"
 x-data="{ periodMode: 'month_range', fromMonth: '10' }">
<div class="space-y-3">
 <div class="flex flex-col">
  <label class="block">Period Customization</label>
  <div class="flex">
   <label><input type="radio" name="period_type" value="month_range" x-model="periodMode"><span>From (Month) to (Month)</span></label>
   <label><input type="radio" name="period_type" value="custom_dates" x-model="periodMode"><span>Custom Dates</span></label>
   <label><input type="radio" name="period_type" value="fy" x-model="periodMode"><span>Full FY</span></label>
  </div>
 </div>
 <div x-show="periodMode === 'month_range'"><label for="f">From (Month)</label>
  <select id="f" name="from_month" x-model="fromMonth"><option value="10">October</option></select></div>
</div>
<button type="submit">Download Excel</button></form></div></div>
"""


class RadioGroupTest(SimpleTestCase):
    def test_radio_buttons_sharing_a_name_are_one_choice(self):
        fields = [
            i["field"]
            for i in drawer_blocks.read(RADIO_DRAWER)["items"]
            if "field" in i
        ]

        period = fields[0]
        self.assertEqual(
            (period["name"], period["kind"], period["label"]),
            ("period_type", "radio", "Period Customization"),
        )
        self.assertEqual(period["value"], "month_range")
        self.assertEqual(
            [(o["value"], o["label"]) for o in period["options"]],
            [
                ("month_range", "From (Month) to (Month)"),
                ("custom_dates", "Custom Dates"),
                ("fy", "Full FY"),
            ],
        )
        # The month fields show while the choice is the month range.
        self.assertEqual(
            fields[1]["showWhen"], [{"field": "period_type", "values": ["month_range"]}]
        )


class DateRangeTest(SimpleTestCase):
    def test_a_date_fields_range_comes_with_it(self):
        drawer = """
        <div data-edify-drawer><div class="drawer-body"><form hx-post="/x">
        <div><label for="d">Completed date</label>
        <input id="d" type="date" name="completed_date" min="2026-10-01" max="2026-11-10"></div>
        </form></div></div>
        """

        field = drawer_blocks.read(drawer)["items"][0]["field"]

        self.assertEqual(
            (field["minDate"], field["maxDate"]), ("2026-10-01", "2026-11-10")
        )
        self.assertNotIn("min", field)


SCRIPTED = """
<div data-edify-drawer><div class="drawer-body"><form hx-post="/my-plan/a1/edit">
<div x-data="{ planDay: '2026-11-20', firstDay: '2026-11-20', get asksWhy() { return this.planDay !== this.firstDay; } }">
<div><label for="day">Planned date</label>
<input id="day" type="date" name="scheduled_date" x-model="planDay" value="2026-11-20" required></div>
<template x-if="asksWhy">
<div data-edit-reason><label for="why">Reason for the change <span>*</span></label>
<textarea id="why" name="reason" required rows="3" placeholder="Why the date is changing"></textarea>
<p class="edify-text-caption">Recorded with the activity.</p></div>
</template>
<template x-if="locked"><div><span>SSA intervention</span><input type="text" readonly :value="label"></div></template>
<template x-if="!locked"><div><label for="focus">Focus intervention</label>
<select id="focus" name="focus_intervention"><option value="">None</option></select></div></template>
<template x-if="namesIntervention"><div><label for="day_focus">SSA intervention</label>
<select id="day_focus" name="day_focus"><option value="">Each school's own</option></select></div></template>
<template x-if="isCourse"><div><label for="course2">Training</label>
<select id="course2" name="course" required><option value="">Select a training</option>
<template x-for="c in courses"><option :value="c.id" x-text="c.label"></option></template></select></div></template>
<template x-if="ceiling.managed"><span>Training ceiling</span></template>
<template x-for="option in options"><div><label for="o">Option</label><input id="o" name="option"></div></template>
</div>
<div x-data="{ kind: 'visit', isTraining: false }">
<div><label for="kind">Kind</label>
<select id="kind" name="kind" x-model="kind"><option value="visit" selected>Visit</option><option value="core">Core</option></select></div>
<template x-if="kind === 'core'"><div><label for="cohort">Cohort</label>
<input id="cohort" type="number" name="cohort" required></div></template>
<template x-if="isTraining"><div><label for="course">Training</label>
<select id="course" name="training_course_id"><option value="">Choose</option></select></div></template>
</div>
<button type="submit">Save changes</button>
</form></div></div>
"""


class ScriptedPartTest(SimpleTestCase):
    """A part the drawer's script adds (``<template x-if>``) is read as a part
    shown when the script would add it."""

    def setUp(self):
        self.items = drawer_blocks.read(SCRIPTED)["items"]
        self.fields = {i["field"]["name"]: i for i in self.items if "field" in i}

    def test_a_part_the_reader_cannot_follow_is_shown_and_optional(self):
        reason = self.fields["reason"]

        self.assertEqual(reason.get("showWhen", []), [])
        self.assertEqual(
            (reason["field"]["label"], reason["field"]["kind"]),
            ("Reason for the change", "textarea"),
        )
        self.assertEqual(reason["field"]["value"], "")
        # The web asks for it only sometimes; the save says when it is needed.
        self.assertFalse(reason["field"]["required"])
        self.assertEqual(reason["field"]["help"], "Recorded with the activity.")

    def test_a_part_shown_for_a_choice_says_which_and_is_required_while_shown(self):
        cohort = self.fields["cohort"]

        self.assertEqual(cohort["showWhen"], [{"field": "kind", "values": ["core"]}])
        self.assertTrue(cohort["field"]["required"])

    def test_a_part_the_script_never_adds_is_left_out(self):
        self.assertNotIn("training_course_id", self.fields)

    def test_two_parts_the_script_chooses_between_are_left_out(self):
        self.assertNotIn("focus_intervention", self.fields)
        self.assertNotIn("", self.fields)

    def test_a_part_with_a_field_the_web_never_insists_on_is_left_out(self):
        # The app could otherwise send a choice the web does not offer then.
        self.assertNotIn("day_focus", self.fields)

    def test_a_part_whose_choices_the_script_draws_is_left_out(self):
        # The app would get a choice list with nothing to choose.
        self.assertNotIn("course", self.fields)

    def test_words_alone_in_a_part_the_reader_cannot_follow_are_left_out(self):
        self.assertNotIn({"text": "Training ceiling"}, self.items)

    def test_a_repeated_row_template_stays_silent(self):
        self.assertNotIn("option", self.fields)

    def test_a_save_sends_the_part_the_drawer_shows(self):
        sent = drawer_blocks.form_data(
            SCRIPTED, {"scheduled_date": "2026-11-21", "reason": "Exams"}
        )

        self.assertEqual(sent, {"scheduled_date": "2026-11-21", "reason": "Exams"})
