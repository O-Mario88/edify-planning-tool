"""The cascade's rules, each tested where it would actually break.

The specification's instructions are mostly prohibitions — do not make the RVP
write every milestone, do not let employees remove mandatory priorities, do not
give every role the same target. A prohibition is only real if something
refuses, so each test below drives the refusal rather than asserting the happy
path around it.
"""

from __future__ import annotations

from datetime import date

from django.contrib.auth import get_user_model
from django.test import TestCase

from apps.accounts.models import StaffProfile
from apps.core.exceptions import BadRequest, Forbidden
from apps.hr import performance_service, priority_cascade
from apps.hr.models import (
    PerformanceCycle,
    PerformancePriority,
    PerformanceReview,
    PriorityAccountability,
    ReviewStage,
    ReviewType,
    StrategicPriority,
    StrategicPriorityLevel,
    StrategicPriorityRoleRule,
    StrategicPriorityStatus,
)

User = get_user_model()
FY = "2026"


class _Principal:
    def __init__(self, user):
        self.user_id = user.id
        self.active_role = user.active_role
        self.staff_profile_id = None


def _user(email, role):
    user = User.objects.create_user(
        email=email,
        password="password123",
        name=email.split("@")[0],
        roles=[role],
        active_role=role,
        is_active=True,
    )
    return user


class CascadeTestCase(TestCase):
    def setUp(self):
        self.rvp = _user("rvp@cascade.test", "RegionalVicePresident")
        self.cd = _user("cd@cascade.test", "CountryDirector")
        self.cceo = _user("cceo@cascade.test", "CCEO")
        self.rvp_p, self.cd_p = _Principal(self.rvp), _Principal(self.cd)

    def _priority(self, *, level, title="Current-FY SSA Coverage", parent=None, **kw):
        return StrategicPriority.objects.create(
            fy=FY,
            level=level,
            parent=parent,
            title=title,
            strategic_purpose=(
                "Every eligible assigned school should have a complete and "
                "verified current-FY SSA."
            ),
            target_guidance="100%",
            **kw,
        )

    def _review(self, user, role="CCEO"):
        staff = StaffProfile.objects.create(user=user, title=role)
        return PerformanceReview.objects.create(
            staff=staff,
            fy=FY,
            review_type=ReviewType.ANNUAL_PRIORITIES,
            period=f"FY{FY}",
            due_date=date(2026, 9, 30),
        )

    def _rule(self, priority, role, accountability, metric, outcome="Do the thing"):
        return StrategicPriorityRoleRule.objects.create(
            priority=priority,
            role=role,
            accountability=accountability,
            metric_key=metric,
            outcome_statement=outcome,
        )

    def _ssa_priority_with_four_roles(self, level=StrategicPriorityLevel.REGIONAL):
        """The specification's own worked example, as data."""
        priority = self._priority(level=level)
        self._rule(
            priority,
            "CCEO",
            PriorityAccountability.EXECUTE,
            "ssa_coverage",
            "Complete allocated SSA work",
        )
        self._rule(
            priority,
            "Program Lead",
            PriorityAccountability.SUPERVISE,
            "team_ssa_coverage",
            "Supervise team SSA coverage",
        )
        self._rule(
            priority,
            "ImpactAssessment",
            PriorityAccountability.VERIFY,
            "ssa_verification_sla",
            "Verify SSA quality and timeliness",
        )
        # Recorded, not omitted — the exemption has to be reviewable.
        self._rule(
            priority,
            "Accountant",
            PriorityAccountability.NOT_APPLICABLE,
            None,
            "Not applicable to the finance role",
        )
        return priority


class RoleTranslationTest(CascadeTestCase):
    """The central rule: one strategy, four different measures."""

    def test_one_priority_gives_each_role_a_different_metric(self):
        priority = self._ssa_priority_with_four_roles()
        priority_cascade.publish(priority, self.rvp_p)

        metrics = {}
        for role in ("CCEO", "Program Lead", "ImpactAssessment"):
            rules = priority_cascade.rules_for_role(role, FY)
            self.assertEqual(len(rules), 1, role)
            metrics[role] = rules[0].metric_key

        self.assertEqual(len(set(metrics.values())), 3, metrics)

    def test_an_exempt_role_receives_nothing(self):
        """The Accountant must not inherit an SSA measure — the spec's
        'must not receive school-visit or SSA-score targets'."""
        priority = self._ssa_priority_with_four_roles()
        priority_cascade.publish(priority, self.rvp_p)
        self.assertEqual(priority_cascade.rules_for_role("Accountant", FY), [])

    def test_the_exemption_is_still_recorded(self):
        """Dropped from agreements, kept in the model: an absent row is
        indistinguishable from somebody forgetting the role exists."""
        priority = self._ssa_priority_with_four_roles()
        rule = priority.role_rules.get(role="Accountant")
        self.assertEqual(rule.accountability, PriorityAccountability.NOT_APPLICABLE)

    def test_accountability_kinds_are_distinguishable(self):
        priority = self._ssa_priority_with_four_roles()
        kinds = {r.role: r.accountability for r in priority.role_rules.all()}
        self.assertEqual(kinds["CCEO"], PriorityAccountability.EXECUTE)
        self.assertEqual(kinds["Program Lead"], PriorityAccountability.SUPERVISE)
        self.assertEqual(kinds["ImpactAssessment"], PriorityAccountability.VERIFY)


class PublicationGateTest(CascadeTestCase):
    def test_a_priority_with_no_role_rules_cannot_publish(self):
        priority = self._priority(level=StrategicPriorityLevel.REGIONAL)
        with self.assertRaises(BadRequest) as caught:
            priority_cascade.publish(priority, self.rvp_p)
        self.assertIn("reaches nobody", str(caught.exception))

    def test_a_carrying_role_without_a_metric_cannot_publish(self):
        """A commitment that can never be evidenced looks measured at the
        conversation and is not — worse than no commitment."""
        priority = self._priority(level=StrategicPriorityLevel.REGIONAL)
        self._rule(priority, "CCEO", PriorityAccountability.EXECUTE, None)
        with self.assertRaises(BadRequest) as caught:
            priority_cascade.publish(priority, self.rvp_p)
        self.assertIn("CCEO", str(caught.exception))

    def test_an_exempt_role_needs_no_metric(self):
        priority = self._priority(level=StrategicPriorityLevel.REGIONAL)
        self._rule(priority, "CCEO", PriorityAccountability.EXECUTE, "ssa_coverage")
        self._rule(priority, "Accountant", PriorityAccountability.NOT_APPLICABLE, None)
        priority_cascade.publish(priority, self.rvp_p)
        priority.refresh_from_db()
        self.assertEqual(priority.status, StrategicPriorityStatus.PUBLISHED)

    def test_a_country_director_cannot_author_regional_direction(self):
        priority = self._ssa_priority_with_four_roles()
        with self.assertRaises(Forbidden):
            priority_cascade.publish(priority, self.cd_p)

    def test_an_rvp_cannot_author_country_priorities(self):
        priority = self._ssa_priority_with_four_roles(
            level=StrategicPriorityLevel.COUNTRY
        )
        with self.assertRaises(Forbidden):
            priority_cascade.publish(priority, self.rvp_p)

    def test_an_unpublished_priority_cascades_to_nobody(self):
        self._ssa_priority_with_four_roles()  # left in draft
        self.assertEqual(priority_cascade.rules_for_role("CCEO", FY), [])


class CountryTranslationTest(CascadeTestCase):
    """A country priority supersedes the regional one it translates."""

    def test_the_country_rule_replaces_its_regional_parent(self):
        regional = self._ssa_priority_with_four_roles()
        priority_cascade.publish(regional, self.rvp_p)

        country = self._priority(
            level=StrategicPriorityLevel.COUNTRY,
            title="Uganda SSA Coverage",
            parent=regional,
        )
        self._rule(
            country,
            "CCEO",
            PriorityAccountability.EXECUTE,
            "ssa_coverage",
            "Complete every assigned school's SSA before Q3",
        )
        priority_cascade.publish(country, self.cd_p)

        rules = priority_cascade.rules_for_role("CCEO", FY)
        self.assertEqual(len(rules), 1, "the CCEO got two commitments for one strategy")
        self.assertEqual(rules[0].priority.level, StrategicPriorityLevel.COUNTRY)

    def test_an_untranslated_regional_priority_still_applies(self):
        """Superseding is per-priority, not wholesale — a country that has not
        yet translated a regional direction must still inherit it."""
        regional = self._ssa_priority_with_four_roles()
        priority_cascade.publish(regional, self.rvp_p)

        other = self._priority(
            level=StrategicPriorityLevel.COUNTRY, title="Country-only priority"
        )
        self._rule(other, "CCEO", PriorityAccountability.EXECUTE, "new_schools")
        priority_cascade.publish(other, self.cd_p)

        metrics = {r.metric_key for r in priority_cascade.rules_for_role("CCEO", FY)}
        self.assertEqual(metrics, {"ssa_coverage", "new_schools"})

    def test_the_regional_intent_stays_traceable(self):
        regional = self._ssa_priority_with_four_roles()
        country = self._priority(
            level=StrategicPriorityLevel.COUNTRY, title="Uganda SSA", parent=regional
        )
        self.assertEqual(country.parent_id, regional.id)
        self.assertIn(country, regional.translations.all())


class WeightRangeTest(CascadeTestCase):
    """Leadership sets bounds; the number inside them is a conversation."""

    def test_a_default_weight_above_the_range_is_clamped(self):
        priority = self._priority(
            level=StrategicPriorityLevel.REGIONAL, weight_min=10, weight_max=25
        )
        rule = self._rule(
            priority, "CCEO", PriorityAccountability.EXECUTE, "ssa_coverage"
        )
        rule.default_weight = 90
        rule.save(update_fields=["default_weight"])
        self.assertEqual(priority_cascade._clamp_weight(rule), 25)

    def test_a_default_weight_below_the_range_is_clamped(self):
        priority = self._priority(
            level=StrategicPriorityLevel.REGIONAL, weight_min=10, weight_max=25
        )
        rule = self._rule(
            priority, "CCEO", PriorityAccountability.EXECUTE, "ssa_coverage"
        )
        rule.default_weight = 1
        rule.save(update_fields=["default_weight"])
        self.assertEqual(priority_cascade._clamp_weight(rule), 10)

    def test_a_backwards_range_is_refused_by_the_database(self):
        from django.db.utils import IntegrityError

        with self.assertRaises(IntegrityError):
            self._priority(
                level=StrategicPriorityLevel.REGIONAL, weight_min=40, weight_max=5
            )


class MandatoryPriorityTest(CascadeTestCase):
    """§2A — employees cannot remove mandatory strategic priorities."""

    def _inherited_row(self, mandatory=True):
        priority = self._priority(
            level=StrategicPriorityLevel.REGIONAL, is_mandatory=mandatory
        )
        rule = self._rule(
            priority, "CCEO", PriorityAccountability.EXECUTE, "ssa_coverage"
        )
        priority_cascade.publish(priority, self.rvp_p)

        review = self._review(self.cceo)
        priority_cascade.apply_to_review(review, "CCEO")
        return review.priorities.get(source_rule=rule)

    def test_a_mandatory_inherited_priority_cannot_be_removed(self):
        row = self._inherited_row(mandatory=True)
        with self.assertRaises(BadRequest) as caught:
            priority_cascade.assert_removable(row)
        self.assertIn("cannot be removed", str(caught.exception))

    def test_an_optional_inherited_priority_can_be_removed(self):
        row = self._inherited_row(mandatory=False)
        priority_cascade.assert_removable(row)  # must not raise

    def test_a_mandatory_priority_metric_cannot_be_repointed(self):
        """Keeping the priority while measuring something else is the
        appearance of the control without the control."""
        row = self._inherited_row(mandatory=True)
        with self.assertRaises(BadRequest):
            priority_cascade.assert_metric_unchanged(row, "new_schools")

    def test_the_same_metric_is_not_treated_as_a_change(self):
        row = self._inherited_row(mandatory=True)
        priority_cascade.assert_metric_unchanged(row, row.metric_key)

    def test_enforcement_survives_the_strategy_being_retired(self):
        """The row carries its OWN mandatory flag, so deleting the rule cannot
        quietly unlock commitments already signed against it."""
        row = self._inherited_row(mandatory=True)
        StrategicPriorityRoleRule.objects.all().delete()
        row.refresh_from_db()
        self.assertIsNone(row.source_rule_id)
        with self.assertRaises(BadRequest):
            priority_cascade.assert_removable(row)


class ApplyToReviewTest(CascadeTestCase):
    def setUp(self):
        super().setUp()
        self.review = self._review(self.cceo)
        self.staff = self.review.staff

    def test_it_renders_one_commitment_per_applicable_rule(self):
        priority = self._ssa_priority_with_four_roles()
        priority_cascade.publish(priority, self.rvp_p)
        added = priority_cascade.apply_to_review(self.review, "CCEO")
        self.assertEqual(added, 1)
        row = self.review.priorities.get()
        self.assertEqual(row.metric_key, "ssa_coverage")
        self.assertEqual(row.priority_layer, "org")
        self.assertTrue(row.is_mandatory)

    def test_re_running_tops_up_rather_than_duplicating(self):
        """HR publishes late and re-cascades; drafts must not be rebuilt by
        hand and must not double up."""
        first = self._ssa_priority_with_four_roles()
        priority_cascade.publish(first, self.rvp_p)
        priority_cascade.apply_to_review(self.review, "CCEO")

        second = self._priority(
            level=StrategicPriorityLevel.REGIONAL, title="Programme Growth"
        )
        self._rule(second, "CCEO", PriorityAccountability.EXECUTE, "new_schools")
        priority_cascade.publish(second, self.rvp_p)

        added = priority_cascade.apply_to_review(self.review, "CCEO")
        self.assertEqual(added, 1)
        self.assertEqual(self.review.priorities.count(), 2)

        again = priority_cascade.apply_to_review(self.review, "CCEO")
        self.assertEqual(again, 0)
        self.assertEqual(self.review.priorities.count(), 2)

    def test_sequences_do_not_collide(self):
        """A second pass numbers on from what is there, rather than restarting
        at 1 and rendering the agreement in an order nobody chose."""
        priority = self._ssa_priority_with_four_roles()
        priority_cascade.publish(priority, self.rvp_p)
        PerformancePriority.objects.create(
            review=self.review, sequence=1, outcome_statement="Pre-existing"
        )
        priority_cascade.apply_to_review(self.review, "CCEO")
        sequences = list(self.review.priorities.values_list("sequence", flat=True))
        self.assertEqual(len(sequences), len(set(sequences)))

    def test_no_published_strategy_adds_nothing(self):
        """The behaviour that existed before the cascade must survive it."""
        self.assertEqual(priority_cascade.apply_to_review(self.review, "CCEO"), 0)

    def test_a_denominator_renders_the_target_with_its_divisor(self):
        priority = self._ssa_priority_with_four_roles()
        priority_cascade.publish(priority, self.rvp_p)
        priority_cascade.apply_to_review(
            self.review, "CCEO", denominators={"ssa_coverage": 12}
        )
        row = self.review.priorities.get()
        self.assertEqual(row.target_number, 12)
        self.assertIn("12", row.denominator_note or "")


class ManagerRoutingTest(TestCase):
    """§3 — who holds the conversation, kept separate from who sets strategy."""

    def test_the_routing_table_matches_the_specification(self):
        expected = {
            "CCEO": "Program Lead",
            "Program Lead": "CountryDirector",
            "ImpactAssessment": "CountryDirector",
            "ProjectCoordinator": "CountryDirector",
            "Accountant": "CountryDirector",
            "CountryDirector": "RegionalVicePresident",
        }
        for role, manager in expected.items():
            with self.subTest(role=role):
                self.assertEqual(priority_cascade.manager_role_for(role), manager)

    def test_a_cceo_is_not_routed_to_the_country_director(self):
        """The instruction is explicit: the CD does not create every CCEO's
        detailed priorities — that belongs to the supervising PL."""
        self.assertNotEqual(
            priority_cascade.manager_role_for("CCEO"), "CountryDirector"
        )

    def test_an_unknown_role_routes_nowhere_rather_than_guessing(self):
        self.assertIsNone(priority_cascade.manager_role_for("NotARole"))


class CoverageReportTest(CascadeTestCase):
    """HR's validation step: was the strategy cascaded, or just published?"""

    def test_a_published_but_unreached_priority_is_reported_inert(self):
        priority = self._ssa_priority_with_four_roles()
        priority_cascade.publish(priority, self.rvp_p)
        report = priority_cascade.coverage_report(FY)
        self.assertEqual(report["inert_count"], 1)
        self.assertTrue(report["priorities"][0]["inert"])

    def test_a_priority_that_reached_an_agreement_is_not_inert(self):
        priority = self._ssa_priority_with_four_roles()
        priority_cascade.publish(priority, self.rvp_p)
        review = self._review(self.cceo)
        priority_cascade.apply_to_review(review, "CCEO")

        report = priority_cascade.coverage_report(FY)
        self.assertEqual(report["inert_count"], 0)
        self.assertEqual(report["priorities"][0]["staff_reached"], 1)


class DraftAgreementIntegrationTest(CascadeTestCase):
    """The cascade has to reach the real draft builder, not just its own API."""

    def test_a_published_priority_appears_on_a_generated_agreement(self):
        from apps.hr.performance_engine import build_draft_agreement

        priority = self._ssa_priority_with_four_roles()
        priority_cascade.publish(priority, self.rvp_p)

        staff = StaffProfile.objects.create(user=self.cceo, title="CCEO")
        cycle = PerformanceCycle.objects.create(fy=FY)
        review = build_draft_agreement(staff, cycle, self.cd_p)

        inherited = review.priorities.filter(source_rule__isnull=False)
        self.assertEqual(inherited.count(), 1)
        self.assertTrue(inherited.first().is_mandatory)

    def test_the_role_template_still_produces_its_own_rows(self):
        """The cascade adds to the agreement; it does not replace the role
        template that was there before it."""
        from apps.hr.performance_engine import build_draft_agreement

        priority = self._ssa_priority_with_four_roles()
        priority_cascade.publish(priority, self.rvp_p)

        staff = StaffProfile.objects.create(user=self.cceo, title="CCEO")
        cycle = PerformanceCycle.objects.create(fy=FY)
        review = build_draft_agreement(staff, cycle, self.cd_p)

        self.assertGreater(
            review.priorities.filter(source_rule__isnull=True).count(), 0
        )


class AgreementWritePathTest(CascadeTestCase):
    """§2A at the place it would actually be violated.

    ``set_priorities`` rebuilds the agreement from whatever the employee
    submits. Before the cascade that was harmless — every row was theirs. With
    inherited rows on the same review it is the removal path, and a guard that
    only exists in the cascade's own API guards nothing.
    """

    def setUp(self):
        super().setUp()
        priority = self._priority(
            level=StrategicPriorityLevel.REGIONAL, is_mandatory=True
        )
        self.rule = self._rule(
            priority, "CCEO", PriorityAccountability.EXECUTE, "ssa_coverage"
        )
        priority_cascade.publish(priority, self.rvp_p)

        self.review = self._review(self.cceo)
        self.review.stage = ReviewStage.PRIORITIES_DRAFT
        self.review.save(update_fields=["stage"])
        priority_cascade.apply_to_review(self.review, "CCEO")
        self.inherited = self.review.priorities.get(source_rule=self.rule)

    def _own(self, weight):
        return {
            "outcome_statement": "Something the employee chose",
            "measures_of_success": "A measure",
            "weight": weight,
        }

    def _keep_inherited(self, weight):
        return {
            "id": self.inherited.id,
            "outcome_statement": self.inherited.outcome_statement,
            "metric_key": self.inherited.metric_key,
            "measures_of_success": "How I will get there",
            "weight": weight,
        }

    def test_a_submission_that_omits_a_mandatory_priority_is_refused(self):
        with self.assertRaises(BadRequest) as caught:
            performance_service.set_priorities(
                self.review.id, self.cceo, [self._own(100)]
            )
        self.assertIn("cannot be removed", str(caught.exception))

    def test_the_refusal_leaves_the_agreement_intact(self):
        """A rejected write must not have half-applied — the old code deleted
        every row before it built the new ones."""
        with self.assertRaises(BadRequest):
            performance_service.set_priorities(
                self.review.id, self.cceo, [self._own(100)]
            )
        self.assertTrue(
            self.review.priorities.filter(id=self.inherited.id).exists(),
            "the mandatory priority was deleted by the write it refused",
        )

    def test_repointing_a_mandatory_metric_is_refused(self):
        row = self._keep_inherited(50)
        row["metric_key"] = "something_easier"
        with self.assertRaises(BadRequest) as caught:
            performance_service.set_priorities(
                self.review.id, self.cceo, [row, self._own(50)]
            )
        self.assertIn("cannot be changed", str(caught.exception))
        # This refusal fires mid-rebuild, after the ordinary rows have already
        # been deleted — so it is the transaction, not the ordering, that has
        # to keep the agreement whole.
        self.inherited.refresh_from_db()
        self.assertEqual(self.inherited.metric_key, "ssa_coverage")

    def test_the_employee_still_owns_the_milestones(self):
        """The commitment is not negotiable; how it gets done is."""
        row = self._keep_inherited(50)
        row["milestones"] = [{"description": "Finish the northern cluster first"}]
        performance_service.set_priorities(
            self.review.id, self.cceo, [row, self._own(50)]
        )
        self.inherited.refresh_from_db()
        self.assertEqual(self.inherited.measures_of_success, "How I will get there")
        self.assertEqual(self.inherited.milestones.count(), 1)

    def test_the_inherited_row_survives_as_the_same_row(self):
        """Not deleted and recreated — its link to the strategy, its evidence
        and its mandatory flag all hang off the identity."""
        performance_service.set_priorities(
            self.review.id, self.cceo, [self._keep_inherited(50), self._own(50)]
        )
        self.inherited.refresh_from_db()
        self.assertEqual(self.inherited.source_rule_id, self.rule.id)
        self.assertTrue(self.inherited.is_mandatory)

    def test_an_ordinary_priority_is_still_freely_rewritten(self):
        performance_service.set_priorities(
            self.review.id, self.cceo, [self._keep_inherited(50), self._own(50)]
        )
        performance_service.set_priorities(
            self.review.id,
            self.cceo,
            [self._keep_inherited(40), self._own(30), self._own(30)],
        )
        self.assertEqual(self.review.priorities.count(), 3)
        self.assertEqual(
            self.review.priorities.filter(is_mandatory=True).count(),
            1,
            "the rewrite duplicated or dropped the inherited row",
        )
