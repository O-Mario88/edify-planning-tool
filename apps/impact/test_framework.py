"""The measurement framework: who defines success, who reviews it, and what a
published rule does and does not change (IA review, owner, 2026-09-13)."""

from __future__ import annotations

from datetime import date, timedelta

from django.core.cache import cache
from django.db import connection
from django.test import Client, TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from apps.accounts.models import StaffProfile, User
from apps.activity_catalogue import intervention_mapping as im
from apps.activity_catalogue.models import (
    ActivityCatalogueItem,
    ActivityInterventionMapping,
    MappingAuthor,
    MappingMode,
    MappingStatus,
)
from apps.audit.models import AuditLog
from apps.core.exceptions import BadRequest, Forbidden
from apps.core.rbac import EdifyRole
from apps.geography.models import District, Region
from apps.impact import framework as fw
from apps.impact.models import DefinitionStatus, OutcomeArea
from apps.schools.models import School
from apps.ssa import change_rules

BACKEND = "apps.accounts.auth_backend.LockoutEnforcingModelBackend"
IA = EdifyRole.IMPACT_ASSESSMENT.value
CD = EdifyRole.COUNTRY_DIRECTOR.value
CB = "christlike_behaviour"
LEAD = "leadership"

LOCMEM = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "ia-framework-tests",
    }
}


def _user(email, role, country="Uganda"):
    user = User.objects.create_user(
        email=email,
        name=email.split("@")[0],
        roles=[role],
        active_role=role,
        password="x",
    )
    StaffProfile.objects.create(user=user, title=role, country=country)
    return User.objects.select_related("staff_profile").get(pk=user.pk)


def _item(code, **extra):
    return ActivityCatalogueItem.objects.create(
        stable_code=code,
        source_name=code,
        display_name=code.replace("_", " ").title(),
        activity_type="training",
        status="active",
        requires_school=True,
        # An active item must be costable and evidenced.
        costing_profile="IN_SCHOOL_TRAINING",
        evidence_profile="TRAINING_ATTENDANCE",
        salesforce_record_type="TRAINING",
        **extra,
    )


def _publish(author, reviewer, item, data):
    mapping = im.save_draft(author, item, data)
    im.submit_for_review(author, mapping, "Set from the FY2026 review.")
    return im.review(reviewer, mapping, decision="approve")


class FrameworkFixture(TestCase):
    def setUp(self):
        self.ia = _user("ia1-fw@t.org", IA)
        self.ia2 = _user("ia2-fw@t.org", IA)
        self.cd = _user("cd-fw@t.org", CD)
        self.item = _item("FW_CHARACTER")


# ── Measurement rules: the review lifecycle ─────────────────────────────────


class RuleLifecycleTests(FrameworkFixture):
    def test_a_draft_changes_nothing_until_a_second_officer_publishes_it(self):
        draft = im.save_draft(self.ia, self.item, {"intervention": CB})

        self.assertFalse(draft.active)
        self.assertEqual(draft.status, MappingStatus.DRAFT)
        self.assertTrue(im.mapping_for(self.item)["needs_mapping"])

        im.submit_for_review(self.ia, draft, "First rule for character training.")
        published = im.review(self.ia2, draft, decision="approve")

        self.assertTrue(published.active)
        self.assertEqual(published.status, MappingStatus.PUBLISHED)
        self.assertEqual(published.approved_by, str(self.ia2.id))
        self.assertEqual(published.review_basis, "peer_ia")
        self.assertEqual(im.mapping_for(self.item)["primary"].id, published.id)

    def test_submitting_needs_a_reason(self):
        draft = im.save_draft(self.ia, self.item, {"intervention": CB})

        with self.assertRaises(BadRequest):
            im.submit_for_review(self.ia, draft, "  ")

    def test_nobody_publishes_a_rule_they_wrote(self):
        draft = im.save_draft(self.ia, self.item, {"intervention": CB})
        im.submit_for_review(self.ia, draft, "Reason")

        with self.assertRaises(Forbidden):
            im.review(self.ia, draft, decision="approve")
        with self.assertRaises(BadRequest):
            # publish() is the reviewer's step and needs a submitted rule.
            im.publish(
                self.ia,
                im.save_draft(self.ia2, _item("FW_OTHER"), {"intervention": CB}),
            )

    def test_the_country_director_acknowledges_only_where_there_is_no_second_officer(
        self,
    ):
        draft = im.save_draft(self.ia, self.item, {"intervention": CB})
        im.submit_for_review(self.ia, draft, "Reason")

        # Uganda has a second officer, so the Country Director may not.
        with self.assertRaises(Forbidden):
            im.review(self.cd, draft, decision="approve")

        self.ia2.is_active = False
        self.ia2.save(update_fields=["is_active"])
        published = im.review(self.cd, draft, decision="approve")

        self.assertEqual(published.review_basis, "cd_fallback")

    def test_the_country_director_still_cannot_write_a_rule(self):
        with self.assertRaises(Forbidden):
            im.save_draft(self.cd, self.item, {"intervention": CB})

    def test_an_officer_in_another_country_does_not_review(self):
        kenya = _user("ia-ke-fw@t.org", IA, "Kenya")
        draft = im.save_draft(self.ia, self.item, {"intervention": CB})
        im.submit_for_review(self.ia, draft, "Reason")

        with self.assertRaises(Forbidden):
            im.review(kenya, draft, decision="approve")

    def test_returning_needs_a_note_and_sends_the_draft_back(self):
        draft = im.save_draft(self.ia, self.item, {"intervention": CB})
        im.submit_for_review(self.ia, draft, "Reason")

        with self.assertRaises(BadRequest):
            im.review(self.ia2, draft, decision="return", note="")
        returned = im.review(
            self.ia2, draft, decision="return", note="Window is too short."
        )

        self.assertEqual(returned.status, MappingStatus.DRAFT)
        self.assertFalse(returned.active)
        self.assertEqual(returned.review_note, "Window is too short.")

    def test_a_new_version_supersedes_the_live_one_and_keeps_it_readable(self):
        first = _publish(
            self.ia, self.ia2, self.item, {"intervention": CB, "follow_up_min_days": 90}
        )
        second = _publish(
            self.ia,
            self.ia2,
            self.item,
            {"intervention": CB, "follow_up_min_days": 180},
        )

        first.refresh_from_db()
        self.assertEqual(first.status, MappingStatus.SUPERSEDED)
        self.assertEqual(first.follow_up_min_days, 90)
        self.assertEqual(second.version, first.version + 1)
        self.assertEqual(len(im.history_for(self.item)), 2)

    def test_every_transition_is_audited(self):
        mapping = _publish(self.ia, self.ia2, self.item, {"intervention": CB})

        actions = set(
            AuditLog.objects.filter(subject_id=mapping.id).values_list(
                "action", flat=True
            )
        )
        self.assertTrue(
            {"ia.mapping.drafted", "ia.mapping.submitted", "ia.mapping.published"}
            <= actions
        )

    def test_a_planner_selects_activity_keeps_its_mode(self):
        # The seeded row says the planner names the intervention.
        seeded = ActivityInterventionMapping.objects.create(
            catalogue_item=self.item,
            intervention=None,
            mapping_mode=MappingMode.ANY_SSA_INTERVENTION,
            authored_by=MappingAuthor.SEED,
        )
        published = _publish(
            self.ia,
            self.ia2,
            self.item,
            {
                "intervention": CB,
                "follow_up_min_days": 120,
                "min_meaningful_change": "0.5",
            },
        )

        seeded.refresh_from_db()
        self.assertEqual(published.mapping_mode, MappingMode.ANY_SSA_INTERVENTION)
        self.assertIsNone(published.intervention)
        self.assertEqual(published.follow_up_min_days, 120)
        self.assertEqual(seeded.status, MappingStatus.SUPERSEDED)
        # The rule applies to whichever intervention the planner chose.
        self.assertEqual(
            change_rules.rule_for_activity(self.item.id, LEAD, country="Uganda").id,
            published.id,
        )

    def test_a_seeded_row_reads_as_a_reference_default(self):
        seeded = ActivityInterventionMapping.objects.create(
            catalogue_item=self.item,
            intervention=CB,
            mapping_mode=MappingMode.FIXED,
            authored_by=MappingAuthor.SEED,
        )

        self.assertTrue(im.is_reference_default(seeded))
        self.assertEqual(fw.rule_state(seeded)[0], im.REFERENCE_DEFAULT_LABEL)


# ── One definition of improved ──────────────────────────────────────────────


class ChangeRuleTests(FrameworkFixture):
    def test_without_a_published_rule_any_change_counts_and_says_so(self):
        result = change_rules.change_between(5.0, 5.1, CB)

        self.assertEqual(result["classification"], change_rules.IMPROVED)
        self.assertEqual(result["rule_label"], change_rules.FALLBACK_LABEL)

    def test_readings_too_close_together_are_not_compared(self):
        result = change_rules.change_between(
            5.0, 7.0, CB, before_on=date(2026, 1, 1), after_on=date(2026, 2, 1)
        )

        self.assertEqual(result["classification"], change_rules.NOT_COMPARABLE)
        self.assertIsNone(result["delta"])

    def test_the_schools_country_rule_comes_before_the_deployment_rule(self):
        _publish(
            self.ia,
            self.ia2,
            self.item,
            {"intervention": CB, "min_meaningful_change": "1.0"},
        )
        book = change_rules.RuleBook()

        uganda = change_rules.change_between(5.0, 5.5, CB, rule=book.rule(CB, "Uganda"))
        kenya = change_rules.change_between(5.0, 5.5, CB, rule=book.rule(CB, "Kenya"))

        self.assertEqual(uganda["classification"], change_rules.NO_CHANGE)
        # Uganda's rule does not govern Kenya's schools.
        self.assertEqual(kenya["classification"], change_rules.IMPROVED)

    def test_a_schools_mean_uses_the_mean_of_its_domain_thresholds(self):
        _publish(
            self.ia,
            self.ia2,
            self.item,
            {"intervention": CB, "min_meaningful_change": "1.0"},
        )
        book = change_rules.RuleBook()

        # CB has ±1.0, LEAD has none (0): the school threshold is 0.5.
        self.assertEqual(book.school_rule([CB, LEAD], "Uganda")["threshold"], 0.5)
        self.assertEqual(
            change_rules.school_change(0.4, [CB, LEAD], book=book, country="Uganda")[
                "classification"
            ],
            change_rules.NO_CHANGE,
        )

    def test_decline_service_uses_the_same_rule_in_both_columns(self):
        from apps.analytics.decline_service import declining_schools
        from apps.ssa.models import SsaRecord, SsaScore

        region = Region.objects.create(name="FW Central", country="Uganda")
        district = District.objects.create(name="FW Dist", region=region)
        school = School.objects.create(
            name="FW School", school_id="FW-1", region=region, district=district
        )
        fy = "2026"
        for year, score, on in (
            ("2025", 6.0, date(2025, 3, 1)),
            (fy, 5.8, date(2026, 3, 1)),
        ):
            record = SsaRecord.objects.create(
                school=school,
                fy=year,
                quarter="Q1",
                average_score=score,
                verification_status="confirmed",
                date_of_ssa=timezone.make_aware(
                    timezone.datetime(on.year, on.month, on.day)
                ),
                uploaded_by="t",
            )
            SsaScore.objects.create(ssa_record=record, intervention=CB, score=score)

        data = declining_schools(self.cd, {"fy": fy})

        # -0.2 under the fallback is a decline in the list AND in the column.
        self.assertEqual(data["totalDeclining"], 1)
        self.assertEqual(data["interventions"][0]["decliningCount"], 1)
        self.assertEqual(data["ruleLabel"], change_rules.FALLBACK_LABEL)


# ── Stamping: an enrolment keeps the rule it was measured under ─────────────


class StampingTests(FrameworkFixture):
    def setUp(self):
        super().setUp()
        from apps.projects.models import Project, ProjectSchoolAssignment
        from apps.ssa.models import SsaRecord, SsaScore

        region = Region.objects.create(name="Stamp Central", country="Uganda")
        district = District.objects.create(name="Stamp Dist", region=region)
        self.school = School.objects.create(
            name="Stamp School", school_id="ST-1", region=region, district=district
        )
        self.project = Project.objects.create(
            name="Stamp", code="STAMP", intervention=CB
        )
        baseline = SsaRecord.objects.create(
            school=self.school,
            fy="2025",
            quarter="Q1",
            average_score=4.0,
            verification_status="confirmed",
            date_of_ssa=timezone.now() - timedelta(days=500),
            uploaded_by="t",
        )
        SsaScore.objects.create(ssa_record=baseline, intervention=CB, score=4.0)
        self.assignment = ProjectSchoolAssignment.objects.create(
            project=self.project,
            school=self.school,
            matched_intervention=CB,
            baseline_ssa=baseline,
            baseline_score=4.0,
            baseline_band="Critical",
        )
        self.other_item = _item("FW_VISIT")

    def _deliver(self, item):
        from apps.activities.models import Activity

        return Activity.objects.create(
            school=self.school,
            project_id=self.project.id,
            catalogue_item=item,
            activity_type="training",
            status="ia_verified",
            fy="2026",
            actual_delivery_date=timezone.now() - timedelta(days=300),
            planned_date=(timezone.now() - timedelta(days=300)).date(),
        )

    def test_the_delivered_activitys_rule_is_stamped_not_any_rule_for_the_intervention(
        self,
    ):
        from apps.projects.handlers import refresh_school_impact

        _publish(
            self.ia,
            self.ia2,
            self.other_item,
            {"intervention": CB, "follow_up_min_days": 30},
        )
        mine = _publish(
            self.ia,
            self.ia2,
            self.item,
            {"intervention": CB, "follow_up_min_days": 200},
        )
        self._deliver(self.item)

        refresh_school_impact(self.school.id)

        self.assignment.refresh_from_db()
        self.assertEqual(self.assignment.mapping_id, mine.id)
        self.assertEqual(self.assignment.mapping_version, mine.version)

    def test_republishing_never_rewrites_a_stamped_enrolment(self):
        from apps.projects.handlers import refresh_school_impact

        first = _publish(
            self.ia,
            self.ia2,
            self.item,
            {"intervention": CB, "follow_up_min_days": 200},
        )
        self._deliver(self.item)
        refresh_school_impact(self.school.id)
        self.assignment.refresh_from_db()
        due = self.assignment.follow_up_due_on

        _publish(
            self.ia, self.ia2, self.item, {"intervention": CB, "follow_up_min_days": 30}
        )
        refresh_school_impact(self.school.id)

        self.assignment.refresh_from_db()
        self.assertEqual(self.assignment.mapping_id, first.id)
        self.assertEqual(self.assignment.follow_up_due_on, due)


# ── Outcome areas, indicators, loan purposes ────────────────────────────────


class DefinitionTests(FrameworkFixture):
    def test_the_proposed_areas_arrive_as_drafts_never_as_approved(self):
        created = fw.propose_default_areas(self.ia)

        self.assertEqual(len(created), 3)
        self.assertTrue(all(a.status == DefinitionStatus.DRAFT for a in created))
        self.assertEqual(
            sorted(created[0].domains.values_list("intervention", flat=True)),
            sorted(fw.PROPOSED_OUTCOME_AREAS[0]["interventions"]),
        )
        # Idempotent.
        self.assertEqual(fw.propose_default_areas(self.ia), [])

    def test_an_area_is_reviewed_by_someone_else_and_a_new_version_supersedes_it(self):
        area = fw.propose_default_areas(self.ia)[0]
        fw.submit(self.ia, area, "Proposed grouping.")
        with self.assertRaises(Forbidden):
            fw.review(self.ia, area, decision="approve")
        approved = fw.review(self.ia2, area, decision="approve")
        self.assertEqual(approved.status, DefinitionStatus.APPROVED)

        v2 = fw.save_outcome_area(
            self.ia2,
            {"name": area.name, "definition": "Sharper.", "interventions": [CB]},
            area=approved,
        )
        fw.submit(self.ia2, v2, "Narrowed to CB.")
        fw.review(self.ia, v2, decision="approve")

        approved.refresh_from_db()
        self.assertEqual(approved.status, DefinitionStatus.SUPERSEDED)
        self.assertEqual(v2.version, 2)

    def test_the_country_director_cannot_define_the_framework(self):
        with self.assertRaises(Forbidden):
            fw.propose_default_areas(self.cd)
        with self.assertRaises(Forbidden):
            fw.save_indicator(self.cd, {"name": "x"})

    def test_an_outcome_indicator_cannot_count_activities(self):
        with self.assertRaises(BadRequest):
            fw.save_indicator(
                self.ia,
                {
                    "name": "Teachers trained",
                    "level": "outcome",
                    "unit": "teachers",
                    "source": "activity",
                    "calculation": "count attendance",
                },
            )

    def test_indicator_versions_are_append_only(self):
        data = {
            "name": "Schools improving CB",
            "level": "outcome",
            "unit": "schools",
            "source": "ssa",
            "calculation": "confirmed pairs improved under the change rule",
        }
        v1 = fw.save_indicator(self.ia, data)
        fw.submit(self.ia, v1, "New indicator")
        fw.review(self.ia2, v1, decision="approve")
        v2 = fw.save_indicator(
            self.ia, {**data, "limitations": "SSA is a proxy"}, indicator=v1
        )

        v1.refresh_from_db()
        self.assertEqual(v1.status, DefinitionStatus.APPROVED)
        self.assertEqual(v1.limitations, "")
        self.assertEqual((v2.key, v2.version), (v1.key, 2))

    def test_approving_a_loan_purpose_measurement_writes_its_profile(self):
        from apps.business_transformation.models import LoanPurpose

        purpose = LoanPurpose.objects.create(code="EDTECH_LAB", label="Computer lab")
        record = fw.save_loan_purpose_measurement(
            self.ia,
            purpose,
            {
                "impact_indicators": "Learners using the lab weekly\nTeachers using it",
                "required_evidence": "Delivery note\nPhotos",
                "verification_method": "Follow-up visit with a check",
                "follow_up_days": "90",
                "change_reason": "Existing purpose had no measure.",
            },
        )
        fw.submit(self.ia, record, "")
        fw.review(self.ia2, record, decision="approve")

        purpose.refresh_from_db()
        self.assertTrue(purpose.measurement_profile_complete)
        self.assertEqual(
            purpose.impact_indicators,
            ["Learners using the lab weekly", "Teachers using it"],
        )
        self.assertEqual(purpose.follow_up_days, 90)


# ── Milestone definitions (apps.hr.priority_services) ───────────────────────


class MilestoneApprovalSeparationTests(TestCase):
    def test_whoever_defined_a_milestone_does_not_approve_it(self):
        from unittest import mock

        from apps.hr import priority_services as ps

        milestone = mock.Mock(pk="ms-1", version=1)
        user = mock.Mock(id="u-1", active_role=CD)
        with mock.patch.object(ps, "defined_by", return_value="u-1"):
            with mock.patch.object(
                ps.PriorityMilestone.objects, "select_for_update"
            ) as sfu:
                sfu.return_value.select_related.return_value.get.return_value = (
                    mock.Mock(
                        pk="ms-1",
                        priority=None,
                        requires_definition=False,
                        definition_status=ps.MilestoneDefinitionStatus.DEFINED,
                        metric_definition_id="m",
                        target_value=1,
                        due_date=date(2026, 9, 30),
                        role_applicability=["CCEO"],
                    )
                )
                with self.assertRaises(Forbidden):
                    ps.approve_milestone(milestone, principal=user)


# ── Pages, drawers, notices, To-Dos ─────────────────────────────────────────


@override_settings(CACHES=LOCMEM)
class FrameworkPageTests(FrameworkFixture):
    def _client(self, user):
        client = Client()
        client.force_login(user, backend=BACKEND)
        return client

    def test_the_page_opens_for_ia_and_the_country_director_only(self):
        for tab in ("areas", "indicators", "rules", "purposes"):
            response = self._client(self.ia).get(f"/ia/framework/?tab={tab}")
            self.assertEqual(response.status_code, 200, tab)
        self.assertContains(
            self._client(self.cd).get("/ia/framework/?tab=rules"), "Measurement rules"
        )
        cceo = _user("cceo-fw@t.org", EdifyRole.CCEO.value)
        body = self._client(cceo).get("/ia/framework/").content.decode()
        self.assertNotIn("data-ia-framework-register", body)

    def test_the_old_register_url_sends_ia_to_the_framework(self):
        response = self._client(self.ia).get("/priorities/ssa-mapping")
        self.assertRedirects(
            response, "/ia/framework/?tab=rules", fetch_redirect_response=False
        )

    def test_only_a_second_reviewer_gets_the_review_form(self):
        draft = im.save_draft(self.ia, self.item, {"intervention": CB})
        im.submit_for_review(self.ia, draft, "Reason")
        url = f"/priorities/ssa-mapping/rules/{draft.id}/review"

        self.assertNotContains(self._client(self.ia).get(url), "Record decision")
        self.assertContains(self._client(self.ia2).get(url), "Record decision")

        self._client(self.ia).post(f"{url}/save", {"decision": "approve"})
        draft.refresh_from_db()
        self.assertEqual(draft.status, MappingStatus.IN_REVIEW)

        self._client(self.ia2).post(f"{url}/save", {"decision": "approve"})
        draft.refresh_from_db()
        self.assertEqual(draft.status, MappingStatus.PUBLISHED)

    def test_framework_definitions_route_through_drawers(self):
        client = self._client(self.ia)
        client.post("/ia/framework/areas/propose")
        area = OutcomeArea.objects.get(code="spiritual-formation")
        client.post(
            f"/ia/framework/area/{area.id}/submit/save",
            {"change_reason": "Proposed grouping"},
        )
        area.refresh_from_db()
        self.assertEqual(area.status, DefinitionStatus.IN_REVIEW)

        # The author's own review POST is refused with a message.
        client.post(
            f"/ia/framework/area/{area.id}/review/save", {"decision": "approve"}
        )
        area.refresh_from_db()
        self.assertEqual(area.status, DefinitionStatus.IN_REVIEW)

        self._client(self.ia2).post(
            f"/ia/framework/area/{area.id}/review/save", {"decision": "approve"}
        )
        area.refresh_from_db()
        self.assertEqual(area.status, DefinitionStatus.APPROVED)

    def test_the_rules_filters_reach_the_register(self):
        _item("FW_SECOND", programme_category="Education")
        body = (
            self._client(self.ia)
            .get("/ia/framework/?tab=rules&programme=Education")
            .content.decode()
        )
        self.assertIn("Fw Second", body)
        self.assertNotIn("Fw Character", body)

    def test_the_review_notice_opens_the_record(self):
        from apps.notifications.services import NotificationLinkResolver

        route, label = NotificationLinkResolver.resolve(
            "ia.framework.review_requested", "ActivityInterventionMapping", "m1", IA
        )
        self.assertEqual(route, "/ia/framework/?tab=rules&open=rule-m1")
        self.assertEqual(label, "Review Definition")

    def test_reviewers_are_notified_and_the_todo_appears(self):
        from apps.impact.framework_todos import framework_todos
        from apps.notifications.models import Notification

        draft = im.save_draft(self.ia, self.item, {"intervention": CB})
        im.submit_for_review(self.ia, draft, "Reason")

        self.assertTrue(
            Notification.objects.filter(
                recipient_id=self.ia2.id,
                source_event_type="ia.framework.review_requested",
            ).exists()
        )
        mine = framework_todos(self.ia, IA, timezone.localdate())
        theirs = framework_todos(self.ia2, IA, timezone.localdate())
        self.assertNotIn("ia-framework-review-rules", {r["id"] for r in mine})
        self.assertIn("ia-framework-review-rules", {r["id"] for r in theirs})

        im.review(self.ia2, draft, decision="return", note="Add a window.")
        self.assertIn(
            "ia-framework-returned",
            {r["id"] for r in framework_todos(self.ia, IA, timezone.localdate())},
        )

    def _count(self, fn):
        cache.clear()
        with CaptureQueriesContext(connection) as ctx:
            fn()
        return len(ctx.captured_queries)

    def test_the_rules_register_and_todos_do_not_grow_per_row(self):
        from apps.impact.framework_todos import framework_todos

        client = self._client(self.ia2)

        def load():
            client.get("/ia/framework/?tab=rules")
            framework_todos(self.ia2, IA, timezone.localdate())

        for n in range(3):
            item = _item(f"FW_BUDGET_{n}")
            draft = im.save_draft(self.ia, item, {"intervention": CB})
            im.submit_for_review(self.ia, draft, "Reason")
        load()
        small = self._count(load)
        for n in range(3, 12):
            item = _item(f"FW_BUDGET_{n}")
            draft = im.save_draft(self.ia, item, {"intervention": CB})
            im.submit_for_review(self.ia, draft, "Reason")
        large = self._count(load)

        self.assertLessEqual(large, small + 2)
