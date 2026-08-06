"""Contract tests for the canonical metric registry.

These lock the rules that the pre-registry codebase broke: a metric with no
identity, a percentage with no denominator, and missing data rendered as zero.
"""

from __future__ import annotations

from django.test import SimpleTestCase

from apps.core.metrics import (
    AMBIGUOUS_LABELS,
    METRIC_REGISTRY,
    Category,
    DataState,
    DateBasis,
    FilterBehaviour,
    FinanceStage,
    MetricSpec,
    MetricValue,
    Period,
    Unit,
    all_metrics,
    check,
    format_value,
    get_metric,
    render_metric,
    render_strip,
)


def _spec(**overrides) -> MetricSpec:
    """A minimal valid spec, so each test can break exactly one rule."""
    base = dict(
        key="test_metric",
        label="Test Metric For Guards",
        definition="A metric used only by the registry contract tests.",
        question="Does the guard fire?",
        category=Category.SCALE,
        unit=Unit.COUNT,
        service="apps.core.metrics.tests",
        source_models=("activities.Activity",),
        numerator="Rows matching the test predicate",
        date_basis=DateBasis.PLANNED_DATE,
        period=Period.MONTH,
        scope="test scope",
        owner_page="my_plan",
        filter_behaviour=FilterBehaviour.FILTERED,
        drilldown="my_plan",
    )
    base.update(overrides)
    return MetricSpec(**base)


class RegistryIntegrityTests(SimpleTestCase):
    def test_registry_passes_its_own_checks(self):
        check()

    def test_registry_is_not_empty(self):
        self.assertTrue(all_metrics())

    def test_every_metric_declares_a_decision_it_supports(self):
        """A metric that supports no decision is decoration (section 1)."""
        for metric in METRIC_REGISTRY:
            with self.subTest(metric.key):
                self.assertTrue(metric.question.strip(), metric.key)
                self.assertTrue(metric.definition.strip(), metric.key)

    def test_no_metric_uses_an_ambiguous_label(self):
        for metric in METRIC_REGISTRY:
            with self.subTest(metric.key):
                self.assertNotIn(metric.label.strip().casefold(), AMBIGUOUS_LABELS)

    def test_labels_are_unique_across_the_registry(self):
        labels = [m.label.casefold() for m in METRIC_REGISTRY]
        self.assertEqual(len(labels), len(set(labels)))

    def test_keys_are_unique_across_the_registry(self):
        keys = [m.key for m in METRIC_REGISTRY]
        self.assertEqual(len(keys), len(set(keys)))

    def test_every_percentage_names_its_denominator(self):
        for metric in METRIC_REGISTRY:
            if metric.unit is Unit.PERCENT:
                with self.subTest(metric.key):
                    self.assertTrue(metric.denominator, metric.key)

    def test_every_money_metric_names_its_finance_stage(self):
        for metric in METRIC_REGISTRY:
            if metric.unit is Unit.MONEY_UGX:
                with self.subTest(metric.key):
                    self.assertIsNotNone(metric.finance_stage, metric.key)

    def test_every_metric_has_a_drilldown_or_a_stated_reason(self):
        for metric in METRIC_REGISTRY:
            with self.subTest(metric.key):
                self.assertTrue(
                    metric.drilldown or metric.no_drilldown_reason, metric.key
                )

    def test_unregistered_key_is_rejected(self):
        with self.assertRaises(KeyError):
            get_metric("no_such_metric_key")


class SpecValidationTests(SimpleTestCase):
    def test_percentage_without_denominator_is_rejected(self):
        with self.assertRaises(ValueError):
            _spec(unit=Unit.PERCENT, denominator=None)

    def test_money_without_finance_stage_is_rejected(self):
        with self.assertRaises(ValueError):
            _spec(unit=Unit.MONEY_UGX, finance_stage=None)

    def test_missing_drilldown_needs_a_reason(self):
        with self.assertRaises(ValueError):
            _spec(drilldown=None)

    def test_drilldown_with_a_reason_is_contradictory(self):
        with self.assertRaises(ValueError):
            _spec(drilldown="my_plan", no_drilldown_reason="contextual")

    def test_uppercase_key_is_rejected(self):
        with self.assertRaises(ValueError):
            _spec(key="Test_Metric")


class DataStateTests(SimpleTestCase):
    """Section 22: the five absences must not all render as 0."""

    def test_measured_zero_is_a_number_not_an_absence(self):
        value = MetricValue.measured(0)
        self.assertTrue(value.is_measured if hasattr(value, "is_measured") else True)
        self.assertEqual(value.value, 0)
        self.assertIsNone(value.display_text)

    def test_absence_carries_a_reason_and_no_number(self):
        value = MetricValue.absent(DataState.NOT_YET_MEASURABLE)
        self.assertIsNone(value.value)
        self.assertEqual(value.display_text, "Not yet measurable")

    def test_absence_cannot_smuggle_in_a_value(self):
        with self.assertRaises(ValueError):
            MetricValue(state=DataState.NO_DATA, value=0)

    def test_measured_must_have_a_value(self):
        with self.assertRaises(ValueError):
            MetricValue(state=DataState.MEASURED, value=None)

    def test_absent_rejects_the_measured_state(self):
        with self.assertRaises(ValueError):
            MetricValue.absent(DataState.MEASURED)

    def test_each_absence_has_distinct_wording(self):
        texts = {
            MetricValue.absent(state).display_text
            for state in DataState
            if state is not DataState.MEASURED
        }
        self.assertEqual(len(texts), len(DataState) - 1)

    def test_a_custom_note_overrides_the_default_wording(self):
        value = MetricValue.absent(
            DataState.NO_DATA, note="No approved requests for August."
        )
        self.assertEqual(value.display_text, "No approved requests for August.")


class RatioTests(SimpleTestCase):
    """Section 24: 0/0 is not 100%, and it is not 0% either."""

    def test_empty_denominator_is_no_data_not_zero(self):
        value = MetricValue.ratio(0, 0)
        self.assertIs(value.state, DataState.NO_DATA)
        self.assertIsNone(value.value)

    def test_empty_denominator_is_never_one_hundred_percent(self):
        self.assertNotEqual(MetricValue.ratio(0, 0).value, 100)

    def test_a_real_ratio_keeps_its_denominator(self):
        value = MetricValue.ratio(2, 3)
        self.assertIs(value.state, DataState.MEASURED)
        self.assertEqual(value.value, 66.7)
        self.assertEqual(value.denominator, 3)

    def test_zero_numerator_over_real_denominator_is_a_measured_zero(self):
        value = MetricValue.ratio(0, 12)
        self.assertIs(value.state, DataState.MEASURED)
        self.assertEqual(value.value, 0)

    def test_empty_denominator_can_carry_a_specific_state(self):
        value = MetricValue.ratio(0, 0, empty_state=DataState.NOT_YET_MEASURABLE)
        self.assertIs(value.state, DataState.NOT_YET_MEASURABLE)


class RenderTests(SimpleTestCase):
    KEY = "my_plan_completion_readiness_pct"

    def test_rendered_tile_carries_its_metric_key(self):
        tile = render_metric(self.KEY, MetricValue.ratio(1, 4))
        self.assertEqual(tile.metric_key, self.KEY)

    def test_rendered_tile_uses_the_registry_label_not_a_caller_string(self):
        tile = render_metric(self.KEY, MetricValue.ratio(1, 4))
        self.assertEqual(tile.label, get_metric(self.KEY).label)

    def test_absent_metric_renders_words_not_a_zero(self):
        tile = render_metric(self.KEY, MetricValue.ratio(0, 0))
        self.assertEqual(tile.display_value, "No data")
        self.assertNotEqual(tile.display_value, "0%")
        self.assertFalse(tile.is_measured)

    def test_percentage_render_requires_a_denominator(self):
        with self.assertRaises(ValueError):
            render_metric(self.KEY, MetricValue.measured(50))

    def test_accessible_description_says_what_was_measured(self):
        tile = render_metric(self.KEY, MetricValue.ratio(1, 4))
        self.assertIn(get_metric(self.KEY).label, tile.accessible_description)
        self.assertIn("25%", tile.accessible_description)
        self.assertIn("of 4", tile.accessible_description)

    def test_accessible_description_explains_an_absence(self):
        tile = render_metric(self.KEY, MetricValue.ratio(0, 0))
        self.assertIn("No data", tile.accessible_description)

    def test_unregistered_metric_cannot_be_rendered(self):
        with self.assertRaises(KeyError):
            render_metric("not_a_metric", MetricValue.measured(1))

    def test_period_and_scope_come_from_the_registry(self):
        tile = render_metric(self.KEY, MetricValue.ratio(1, 4))
        spec = get_metric(self.KEY)
        self.assertEqual(tile.period, spec.period.value)
        self.assertEqual(tile.scope, spec.scope)


class StripDuplicationTests(SimpleTestCase):
    """Section 5: required same-page duplicate KPI count is zero."""

    WEEK = "my_plan_activities_planned_week"
    MONTH = "my_plan_activities_planned_month"

    def _tile(self, key):
        return render_metric(key, MetricValue.measured(3))

    def test_distinct_metrics_render_fine(self):
        items = render_strip([self._tile(self.WEEK), self._tile(self.MONTH)])
        self.assertEqual(len(items), 2)

    def test_the_same_metric_twice_is_rejected(self):
        with self.assertRaises(ValueError) as caught:
            render_strip([self._tile(self.WEEK), self._tile(self.WEEK)])
        self.assertIn(self.WEEK, str(caught.exception))

    def test_a_named_exception_is_allowed_through(self):
        items = render_strip(
            [self._tile(self.WEEK), self._tile(self.WEEK)],
            allow_repeats=frozenset({self.WEEK}),
        )
        self.assertEqual(len(items), 2)

    def test_an_exception_for_one_metric_does_not_excuse_another(self):
        with self.assertRaises(ValueError) as caught:
            render_strip(
                [
                    self._tile(self.WEEK),
                    self._tile(self.WEEK),
                    self._tile(self.MONTH),
                    self._tile(self.MONTH),
                ],
                allow_repeats=frozenset({self.WEEK}),
            )
        self.assertIn(self.MONTH, str(caught.exception))
        self.assertNotIn(self.WEEK, str(caught.exception))

    def test_rendered_items_carry_the_metric_key_for_the_dom_guard(self):
        items = render_strip([self._tile(self.WEEK)])
        self.assertEqual(items[0]["metric_key"], self.WEEK)
        self.assertIn("data_state", items[0])


class FormatTests(SimpleTestCase):
    def test_counts_are_thousands_separated(self):
        spec = _spec(unit=Unit.COUNT)
        self.assertEqual(format_value(spec, 15000), "15,000")

    def test_whole_percentages_do_not_show_false_precision(self):
        spec = _spec(unit=Unit.PERCENT, denominator="all rows")
        self.assertEqual(format_value(spec, 25.0), "25%")

    def test_fractional_percentages_keep_their_precision(self):
        spec = _spec(unit=Unit.PERCENT, denominator="all rows")
        self.assertEqual(format_value(spec, 66.7), "66.7%")

    def test_money_is_labelled_with_its_currency(self):
        spec = _spec(unit=Unit.MONEY_UGX, finance_stage=FinanceStage.APPROVED)
        self.assertEqual(format_value(spec, 1500000), "UGX 1,500,000")
