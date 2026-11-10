"""The planning drawers' reader: the script's starting values, the parts the
drawer draws, and what a save may send."""

from django.test import SimpleTestCase

from apps.mobile_feed import planning_drawers

ASSIGN = """
<div data-edify-drawer>
  <h2 id="drawer-title">Assign Feed School to a partner</h2>
  <div class="drawer-body">
  <form hx-post="/planning/assign-partner-action" x-data="{
    purposeOfVisit: '',
    partnerId: '',
    trainingActivities: [{&quot;id&quot;: &quot;t1&quot;, &quot;label&quot;: &quot;Accounting&quot;, &quot;stableCode&quot;: &quot;ACC&quot;, &quot;ssaIntervention&quot;: &quot;financial_health&quot;, &quot;plannerChooses&quot;: false, &quot;universal&quot;: false, &quot;staffDeliveryAllowed&quot;: true, &quot;priorityTitles&quot;: []}],
    partnerCourses: {&quot;p1&quot;: [&quot;ACC&quot;]},
    followUpActivities: [],
    followUpRequiresTraining: true,
    get showTraining() { return this.purposeOfVisit === 'in_school_training'; },
  }">
    <input type="hidden" name="csrfmiddlewaretoken" value="secret">
    <input type="hidden" name="school_id" value="FEED-1">
    <input type="hidden" name="catalogue_item_id" :value="catalogueItemId">
    <div class="space-y-1">
      <label for="partner_id">Partner <span class="text-rose-500">*</span></label>
      <select name="partner_id" id="partner_id" required>
        <option value="">Select partner…</option>
        <option value="p1">Build Africa</option>
      </select>
    </div>
    <div class="space-y-1">
      <label for="purpose_of_visit">Reason for assigning <span>*</span></label>
      <select name="purpose_of_visit" id="purpose_of_visit">
        <option value="">Select a reason…</option>
        <option value="in_school_training">In-school Training</option>
        <option value="ssa_support" disabled>SSA Support — not available</option>
      </select>
      <p data-visit-locked-reason role="note">SSA Support is already collected.</p>
    </div>
    <div data-assigned-date>
      <span>Assigned date</span><div>10 Nov 2026</div><p>The partner chooses the date.</p>
    </div>
    <p>Monitored by <span>Ada L.</span>, who stays responsible for this support.</p>
    <div class="drawer-footer">
      <button type="button" @click="requestClose()">Cancel</button>
      <button type="submit">Assign to partner</button>
    </div>
  </form>
  </div>
</div>
"""

TOAST = """
<div hx-swap-oob="beforeend:#toast-container">
<div x-data="{ show: true }" data-planning-saved-toast data-undo-toast>
  <span>Assigned to Build Africa. The partner schedules it from here. <a href="/partner-oversight/">Open Partner Oversight</a></span>
  <button type="button">Undo</button>
  <button type="button" aria-label="Dismiss notification">&times;</button>
</div>
</div>
"""


class ScriptValuesTest(SimpleTestCase):
    def test_reads_json_lists_objects_flags_and_quoted_strings(self):
        values = planning_drawers.script_values(
            '{ purpose: \'ssa_support\', list: [1, 2], map: {"a": ["b"]}, '
            "flag: true,\n reason: 'It\\u0027s Critical at 4.6/10.' }"
        )

        self.assertEqual(values["purpose"], "ssa_support")
        self.assertEqual(values["list"], [1, 2])
        self.assertEqual(values["map"], {"a": ["b"]})
        self.assertIs(values["flag"], True)
        self.assertEqual(values["reason"], "It's Critical at 4.6/10.")

    def test_leaves_out_getters_and_functions(self):
        values = planning_drawers.script_values(
            "{ get shown() { return true; }, pick(id) { this.id = id; } }"
        )

        self.assertEqual(values, {})


class ReadAssignTest(SimpleTestCase):
    def test_reads_the_drawer_and_the_values_its_script_starts_with(self):
        drawer = planning_drawers.read_assign(ASSIGN)

        self.assertEqual(drawer["title"], "Assign Feed School to a partner")
        self.assertEqual(drawer["submitLabel"], "Assign to partner")
        self.assertEqual([p["label"] for p in drawer["partners"]], ["Build Africa"])
        self.assertEqual(
            [(p["value"], p["disabled"]) for p in drawer["purposes"]],
            [("in_school_training", False), ("ssa_support", True)],
        )
        self.assertEqual(drawer["purposeNotes"], ["SSA Support is already collected."])
        self.assertEqual(drawer["trainings"][0]["ssaIntervention"], "financial_health")
        self.assertEqual(drawer["partnerCourses"], {"p1": {"codes": ["ACC"]}})
        self.assertTrue(drawer["followUpRequiresTraining"])
        self.assertEqual(drawer["labels"]["partner_id"], "Partner")
        self.assertEqual(drawer["placeholders"]["partner_id"], "Select partner…")
        self.assertEqual(drawer["captions"]["assignedDate"], "10 Nov 2026")
        self.assertEqual(
            drawer["captions"]["monitoredBy"],
            "Monitored by Ada L., who stays responsible for this support.",
        )

    def test_hidden_values_are_the_rendered_ones_only(self):
        drawer = planning_drawers.read_assign(ASSIGN)

        self.assertEqual(drawer["hidden"], {"school_id": "FEED-1"})


class FormDataTest(SimpleTestCase):
    def test_sends_the_drawers_fields_and_its_rendered_hidden_values(self):
        sent = planning_drawers.form_data(
            "assign",
            ASSIGN,
            {
                "partner_id": "p1",
                "catalogue_item_id": "t1",
                "school_id": "SOMEONE-ELSE",
                "monitoring_staff_id": "me",
            },
        )

        self.assertEqual(
            sent,
            {"partner_id": "p1", "catalogue_item_id": "t1", "school_id": "FEED-1"},
        )


class ToastMessageTest(SimpleTestCase):
    def test_is_the_cards_sentence_without_its_buttons(self):
        self.assertEqual(
            planning_drawers.toast_message(TOAST),
            "Assigned to Build Africa. The partner schedules it from here.",
        )
