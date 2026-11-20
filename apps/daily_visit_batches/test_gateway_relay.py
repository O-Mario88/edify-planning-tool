"""The two doors the Go gateway's visit save asks (gateway_relay): closed
without the internal key, and refusing what they were not built for before
any record is read. Their answers on real data are proved by the shadow run
(docs/migration/27 §27.9)."""

from __future__ import annotations

import json

from django.test import RequestFactory, SimpleTestCase, override_settings

from apps.daily_visit_batches import gateway_relay

KEY = "k" * 40


def _post(view, body, key=KEY):
    request = RequestFactory().post(
        "/", data=json.dumps(body), content_type="application/json"
    )
    if key:
        request.META["HTTP_X_EDIFY_INTERNAL_KEY"] = key
    return view(request)


class GatewayRelayDoorsTest(SimpleTestCase):
    @override_settings(EDIFY_INTERNAL_KEY="")
    def test_both_doors_are_closed_while_no_key_is_configured(self):
        for view in (
            gateway_relay.visit_day_check,
            gateway_relay.visit_move_check,
            gateway_relay.visit_cancel_check,
            gateway_relay.costs_to_follow,
            gateway_relay.activity_changed,
            gateway_relay.visit_completed,
        ):
            self.assertEqual(_post(view, {}).status_code, 404)

    @override_settings(EDIFY_INTERNAL_KEY=KEY)
    def test_a_request_without_the_key_is_refused(self):
        for view in (
            gateway_relay.visit_day_check,
            gateway_relay.visit_move_check,
            gateway_relay.visit_cancel_check,
            gateway_relay.costs_to_follow,
            gateway_relay.activity_changed,
            gateway_relay.visit_completed,
        ):
            self.assertEqual(_post(view, {}, key="wrong").status_code, 403)

    @override_settings(EDIFY_INTERNAL_KEY=KEY)
    def test_the_day_check_takes_only_the_probe_fields(self):
        answer = _post(
            gateway_relay.visit_day_check, {"activity": {"est_cost_cents": 5}}
        )
        self.assertEqual(answer.status_code, 400)
        self.assertEqual(json.loads(answer.content)["reason"], "unknown_fields")

    @override_settings(EDIFY_INTERNAL_KEY=KEY)
    def test_the_settle_door_takes_a_short_list_of_row_ids(self):
        for rows in ([], ["1"], [0], list(range(1, 30)), None):
            answer = _post(gateway_relay.costs_to_follow, {"rows": rows})
            self.assertEqual(answer.status_code, 400, rows)

    @override_settings(EDIFY_INTERNAL_KEY=KEY)
    def test_the_move_check_takes_an_activity_a_day_and_a_short_reason(self):
        for body, reason in (
            ({"scheduledDate": "2026-11-20"}, "bad_fields"),
            ({"activityId": "x" * 31, "scheduledDate": "2026-11-20"}, "bad_fields"),
            (
                {"activityId": "a", "scheduledDate": "2026-11-20", "reason": 5},
                "bad_fields",
            ),
            (
                {
                    "activityId": "a",
                    "scheduledDate": "2026-11-20",
                    "reason": "r" * 2001,
                },
                "bad_fields",
            ),
            ({"activityId": "a", "scheduledDate": "20 Nov"}, "bad_date"),
        ):
            answer = _post(gateway_relay.visit_move_check, body)
            self.assertEqual(answer.status_code, 400, body)
            self.assertEqual(json.loads(answer.content)["reason"], reason, body)

    @override_settings(EDIFY_INTERNAL_KEY=KEY)
    def test_the_cancel_check_takes_an_activity_and_a_reason_that_fits(self):
        for body in (
            {"reason": "r"},
            {"activityId": "x" * 31, "reason": "r"},
            {"activityId": "a", "reason": 5},
            {"activityId": "a", "reason": "r" * 513},
        ):
            answer = _post(gateway_relay.visit_cancel_check, body)
            self.assertEqual(answer.status_code, 400, body)
            self.assertEqual(json.loads(answer.content)["reason"], "bad_fields", body)

    @override_settings(EDIFY_INTERNAL_KEY=KEY)
    def test_the_announcement_takes_one_activity_id(self):
        for body in (
            {},
            {"activityId": ""},
            {"activityId": "x" * 31},
            {"activityId": 5},
        ):
            answer = _post(gateway_relay.activity_changed, body)
            self.assertEqual(answer.status_code, 400, body)
            self.assertEqual(json.loads(answer.content)["reason"], "bad_fields", body)


class ClusterPreviewInputsTest(SimpleTestCase):
    """A cluster Group Training's day check (docs/migration/38) asks the cost
    preview what `_create` asks it: the cluster's district for the officer,
    the head count the save derived, and its materials with a blank as 0."""

    def test_the_probe_takes_the_sessions_own_columns(self):
        for field in (
            "cluster_id",
            "expected_participants",
            "schools_invited",
            "printing_pages",
            "photocopy_copies",
        ):
            self.assertIn(field, gateway_relay.PROBE_FIELDS)
        self.assertNotIn("est_cost_cents", gateway_relay.PROBE_FIELDS)

    def test_the_preview_reads_the_cluster_and_the_head_count(self):
        from types import SimpleNamespace
        from unittest import mock

        district = SimpleNamespace(id="d1")
        cluster = SimpleNamespace(district_id="d1", district=district)
        activity = SimpleNamespace(
            cluster_id="c1",
            responsible_staff_id="s1",
            expected_participants=9,
            printing_pages=None,
            photocopy_pages=12,
            photocopy_copies=None,
        )
        with (
            mock.patch("apps.clusters.models.Cluster.objects") as clusters,
            mock.patch(
                "apps.daily_visit_batches.districts.district_type_for_staff",
                return_value="secondary",
            ) as district_type,
        ):
            clusters.select_related.return_value.filter.return_value.first.return_value = cluster
            inputs = gateway_relay._cluster_preview_inputs(activity)

        district_type.assert_called_once_with("s1", district)
        self.assertEqual(
            inputs,
            {
                "districtType": "secondary",
                "expectedParticipants": 9,
                "printingPages": 0,
                "photocopyPages": 12,
                "photocopyCopies": 0,
            },
        )


class OnlineCostTest(SimpleTestCase):
    """An online Group Training's day check (docs/migration/48) asks no
    preview: it answers the UGX 0 cost revision `_price_activity` writes,
    from the input `_costing_input` builds with what `_create` holds."""

    def test_the_probe_takes_the_delivery_mode(self):
        self.assertIn("programme_delivery_mode", gateway_relay.PROBE_FIELDS)

    def test_the_revision_is_free_and_read_from_calculate_dual(self):
        from types import SimpleNamespace
        from unittest import mock

        activity = SimpleNamespace(
            fy="2027",
            responsible_staff_id="s1",
            expected_participants=9,
            printing_pages=None,
            photocopy_pages=None,
            photocopy_copies=None,
        )
        card = SimpleNamespace(id="card", version=3)
        dual = {
            "operationalCard": card,
            "referenceCard": None,
            "reference": None,
            "inputs": {"fy": "2027", "expectedParticipants": 9},
            "warnings": [
                "Regional Standard Funding Rate Card has not been configured."
            ],
        }
        with (
            mock.patch(
                "apps.activities.services._costing_input",
                return_value={"fy": "2027"},
            ) as costing_input,
            mock.patch(
                "apps.budget.costing_service.calculate_dual", return_value=dual
            ) as calculate,
            mock.patch("apps.activities.services._funding_owner_id", return_value="u1"),
        ):
            answer = gateway_relay._online_cost(activity)

        costing_input.assert_called_once_with(
            activity,
            {
                "expectedParticipants": 9,
                "printingPages": 0,
                "photocopyPages": 0,
                "photocopyCopies": 0,
            },
        )
        calculate.assert_called_once_with({"fy": "2027"})
        self.assertEqual(
            answer,
            {
                "operationalCardId": "card",
                "operationalCardVersion": 3,
                "referenceCardId": None,
                "referenceCardVersion": None,
                "referenceCost": None,
                "referenceBreakdown": [],
                "operationalCost": 0,
                "operationalBreakdown": [],
                "calculationInputs": dual["inputs"],
                "warnings": dual["warnings"],
                "missingConfiguration": [],
                "costMissing": False,
                "calculatedBy": "u1",
            },
        )

    @override_settings(EDIFY_INTERNAL_KEY=KEY)
    def test_the_completion_door_takes_an_activity_a_person_and_a_role(self):
        for body in (
            {},
            {"activityId": "a", "userId": "u"},
            {"activityId": "", "userId": "u", "role": "CCEO"},
            {"activityId": "x" * 31, "userId": "u", "role": "CCEO"},
            {"activityId": "a", "userId": 5, "role": "CCEO"},
        ):
            answer = _post(gateway_relay.visit_completed, body)
            self.assertEqual(answer.status_code, 400, body)
            self.assertEqual(json.loads(answer.content)["reason"], "bad_fields", body)
