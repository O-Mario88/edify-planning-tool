"""The interaction inventory is complete, current, and ratchets test evidence.

Three gates (2026-09-24 live-performance audit, interaction manifest):

* the committed manifest matches the live templates and routes, so a control
  added without regenerating it fails here;
* no control's destination resolves to nothing — a form or link to a path
  with no route is a dead control (two were found this way: the closure
  workspace's Close & Lock and Reopen forms posted to trailing-slash paths
  that 404);
* the count of controls with no automated evidence never rises. A new
  control arrives with a test that requests its route, or the ceiling below
  is raised in review where everyone can see it.
"""

from __future__ import annotations

import json

from django.test import SimpleTestCase

from apps.system_health.interaction_inventory import (
    DYNAMIC_DESTINATIONS,
    MANIFEST,
    build_interaction_inventory,
    resolve_route,
)

#: Controls with no automated evidence at 2026-09-24. Lower it as evidence is
#: added; raising it is a reviewed decision, never a way to get CI green.
UNTESTED_CEILING = 363
#: State-changing controls with no automated evidence at 2026-09-24.
UNTESTED_STATE_CHANGING_CEILING = 26


class InteractionInventoryTest(SimpleTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.inventory = build_interaction_inventory()

    def test_the_committed_manifest_matches_the_live_platform(self):
        committed = json.loads(MANIFEST.read_text(encoding="utf-8"))
        live = json.loads(json.dumps(self.inventory))
        if committed != live:
            committed_ids = {c["id"] for c in committed["controls"]}
            live_ids = {c["id"] for c in live["controls"]}
            self.fail(
                "docs/platform-interaction-inventory.json is stale; run "
                "`python manage.py build_interaction_inventory`. "
                f"New controls: {sorted(live_ids - committed_ids)[:10]}; "
                f"removed: {sorted(committed_ids - live_ids)[:10]}."
            )

    def test_every_control_has_a_stable_unique_id(self):
        ids = [c["id"] for c in self.inventory["controls"]]
        self.assertEqual(len(ids), len(set(ids)))

    def test_no_control_points_at_a_path_with_no_route(self):
        dead = [
            (c["template"], c["line"], c["method"], c["destination"])
            for c in self.inventory["controls"]
            if c["destination"].startswith("/") and not c["destination_route"]
        ]
        self.assertEqual(dead, [])

    def test_every_expansion_of_a_dynamic_destination_is_a_route(self):
        for pattern, expansions in DYNAMIC_DESTINATIONS.items():
            for path in expansions:
                with self.subTest(pattern=pattern, path=path):
                    self.assertTrue(resolve_route(path), path)

    def test_untested_controls_never_increase(self):
        summary = self.inventory["summary"]
        self.assertLessEqual(summary["untested"], UNTESTED_CEILING)
        self.assertLessEqual(
            summary["untested_state_changing"], UNTESTED_STATE_CHANGING_CEILING
        )

    def test_the_resolver_reads_templated_destinations(self):
        self.assertEqual(
            resolve_route("/activities/{{ act.id }}/closure/close"),
            "/activities/<str:activity_id>/closure/close",
        )
        self.assertEqual(resolve_route("/activities/{{ act.id }}/closure/close/"), "")
        self.assertEqual(
            resolve_route("/loans/export.csv\n     ?{{ filter_query }}"),
            "/loans/export.csv",
        )
