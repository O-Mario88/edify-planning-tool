"""Training materials by the page (owner, 2026-09-15).

"Add the input fields for printing training material (pages), which will
be multiplied by the number of pages, and photocopying (pages x cost of
photocopying x number of copies). If it is not filled, or left at zero, it
does not fetch the cost for printing."
"""

from __future__ import annotations

from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

from apps.activities.services import MATERIALS_INPUT_KEYS, _validated_materials
from apps.budget.costing import materials_quantities
from apps.core.exceptions import BadRequest


class MaterialsValidationTest(SimpleTestCase):
    def test_blank_is_zero_and_zero_is_no_materials(self):
        self.assertEqual(
            _validated_materials({}),
            {"printingPages": 0, "photocopyPages": 0, "photocopyCopies": 0},
        )
        self.assertEqual(
            _validated_materials(
                {"printingPages": "", "photocopyPages": None, "photocopyCopies": "0"}
            ),
            {"printingPages": 0, "photocopyPages": 0, "photocopyCopies": 0},
        )
        self.assertEqual(
            _validated_materials(
                {"printingPages": " 12 ", "photocopyPages": 4, "photocopyCopies": "30"}
            ),
            {"printingPages": 12, "photocopyPages": 4, "photocopyCopies": 30},
        )

    def test_a_number_that_is_not_a_whole_number_is_refused_by_name(self):
        for key in MATERIALS_INPUT_KEYS:
            for bad in ("2.5", "ten", "-1", "10000000"):
                with self.subTest(key=key, bad=bad), self.assertRaises(BadRequest):
                    _validated_materials({key: bad})

    def test_the_engine_reads_the_same_quantities(self):
        self.assertEqual(materials_quantities({}), (0, 0))
        self.assertEqual(
            materials_quantities(
                {"printingPages": "12", "photocopyPages": "4", "photocopyCopies": "30"}
            ),
            (12, 120),
        )
        # Pages without copies, or copies without pages, is no photocopying.
        self.assertEqual(materials_quantities({"photocopyPages": 4}), (0, 0))
        self.assertEqual(materials_quantities({"photocopyCopies": 30}), (0, 0))
        self.assertEqual(materials_quantities({"printingPages": "-3"}), (0, 0))


class MaterialsDrawerMarkupTest(SimpleTestCase):
    def _read(self, relative: str) -> str:
        return (Path(settings.BASE_DIR) / relative).read_text()

    def test_both_cluster_drawers_ask_for_pages_and_copies(self):
        partial = self._read(
            "templates/partials/clusters/training_materials_fields.html"
        )
        for needle in (
            'name="printing_pages"',
            'name="photocopy_pages"',
            'name="photocopy_copies"',
            "Leave blank or 0 for no materials cost",
        ):
            self.assertIn(needle, partial)
        # Copies follow the participant total until the planner types one.
        self.assertIn(':value="copies"', partial)
        self.assertIn("copiesTouched = true", partial)

        planner = self._read(
            "templates/partials/clusters/cluster_action_planner_drawer.html"
        )
        planning = self._read(
            "templates/partials/planning/schedule_cluster_drawer.html"
        )
        # Once for a training and once for a meeting in the planner; once in
        # the planning drawer, which has no live cost preview.
        self.assertEqual(
            planner.count(
                '{% include "partials/clusters/training_materials_fields.html" '
                "with materials_preview=True %}"
            ),
            2,
        )
        self.assertEqual(
            planning.count(
                '{% include "partials/clusters/training_materials_fields.html" %}'
            ),
            1,
        )
        for source in (planner, planning):
            for state in ("printingPages:", "photocopyPages:", "photocopyCopies:"):
                self.assertIn(state, source)

    def test_the_per_school_fields_are_not_required(self):
        """A blank per-school field counts as zero (owner, 2026-09-15), so
        the browser must not refuse the form before the service can read
        it that way."""
        for relative in (
            "templates/partials/clusters/cluster_action_planner_drawer.html",
            "templates/partials/planning/schedule_cluster_drawer.html",
        ):
            source = self._read(relative)
            with self.subTest(template=relative):
                self.assertIn('name="teachers_per_school"', source)
                self.assertNotIn('step="1" required', source)
                self.assertNotIn('step="1"\n          required', source)
                self.assertIn("counts as 0", source)
