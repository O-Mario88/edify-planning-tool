"""A field's display label read from a table built once (2026-10-26 export
speed work).

Django's ``get_FOO_display()`` rebuilds the field's whole choice table on every
call. My Plan calls it four times a row: 63,000 calls and 2.6 s for a
country's export. ``choice_label`` answers the same words from a table built
once per field.
"""

from __future__ import annotations

from django.test import SimpleTestCase

from apps.activities.models import Activity
from apps.core.choice_labels import choice_label


class ChoiceLabelTests(SimpleTestCase):
    def test_every_activity_type_reads_as_django_reads_it(self):
        for value, _label in Activity._meta.get_field("activity_type").flatchoices:
            activity = Activity(activity_type=value)

            self.assertEqual(
                choice_label(activity, "activity_type"),
                activity.get_activity_type_display(),
            )

    def test_a_value_outside_the_choices_reads_as_itself(self):
        activity = Activity(activity_type="no_such_type")

        self.assertEqual(choice_label(activity, "activity_type"), "no_such_type")
        self.assertEqual(
            choice_label(activity, "activity_type"),
            activity.get_activity_type_display(),
        )

    def test_a_blank_value_reads_as_django_reads_it(self):
        activity = Activity(focus_intervention="")

        self.assertEqual(
            choice_label(activity, "focus_intervention"),
            activity.get_focus_intervention_display(),
        )
