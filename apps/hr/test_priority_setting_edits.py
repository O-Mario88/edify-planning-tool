"""Editing and removing priorities from the Priority Setting tab.

Owner (2026-09-14): "Priority setting is in CD but cannot be edited. Make
sure the numbers/targets are editable from CD and IA only. The PL gets the
number they need to distribute to their team members. Add an Edit button at
the end of each priority. Actually CD and IA can edit or delete a priority in
case they don't want to work on that specific priority this FY."

Each rule is driven where it would break: the roles the matrix lets edit can,
the Program Lead cannot and sees no control, a published figure needs a
reason and leaves distributed allocations alone, a sub-target split cannot
exceed its total, and a milestone with a distributed target does not leave
the FY.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase

from apps.audit.models import AuditLog
from apps.core.exceptions import BadRequest
from apps.hr.models import (
    MilestoneAllocation,
    MilestoneMetricDefinition,
    PriorityMilestone,
    StrategicPriority,
    StrategicPriorityCycle,
    StrategicPriorityRoleRule,
)
from apps.hr.priority_services import (
    MILESTONE_REMOVED,
    MILESTONE_TARGETS_EDITED,
    PRIORITY_REMOVED,
    edit_milestone_targets,
    remove_milestone,
    remove_priority,
)

User = get_user_model()
FY = "2027"


def _user(email, role):
    return User.objects.create_user(
        email=email,
        password="password123",
        name=email.split("@")[0],
        roles=[role],
        active_role=role,
        is_active=True,
    )


class PrioritySettingFixture(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.cd = _user("cd@setting.test", "CountryDirector")
        cls.ia = _user("ia@setting.test", "ImpactAssessment")
        cls.pl = _user("pl@setting.test", "Program Lead")
        cls.hr = _user("hr@setting.test", "HumanResources")
        # A migration may already have opened this FY's cycle; the tests add
        # their own priority group to whichever cycle carries the year.
        cls.cycle, _ = StrategicPriorityCycle.objects.get_or_create(
            financial_year=FY,
            defaults={"title": f"FY{FY} priorities", "status": "draft"},
        )
        cls.metric = MilestoneMetricDefinition.objects.create(
            metric_key="setting_test_metric", canonical_label="Schools reached"
        )

    def _priority(self, code="SETTING_TEST_GROUP", *, status="draft", sequence=1):
        return StrategicPriority.objects.create(
            cycle=self.cycle,
            code=code,
            fy=FY,
            level="country",
            country_id="Uganda",
            title=code.replace("_", " ").title(),
            strategic_purpose="test",
            status=status,
            sequence=sequence,
        )

    def _milestone(self, priority, code="SCHOOLS_REACHED", **overrides):
        fields = {
            "priority": priority,
            "code": code,
            "title": f"Milestone {code}",
            "source_text": f"{code} — 100",
            "milestone_type": "output",
            "measurement_type": "count",
            "progress_source": "test",
            "metric_definition": self.metric,
            "target_value": Decimal("100"),
            "target_unit": "schools",
            "core_target": Decimal("40"),
            "client_target": Decimal("60"),
            "allocation_method": "field_cascade",
            "requires_definition": False,
            "definition_status": "approved",
            "active": True,
        }
        fields.update(overrides)
        return PriorityMilestone.objects.create(**fields)

    def _allocation(self, milestone, *, status="approved", target="30"):
        return MilestoneAllocation.objects.create(
            milestone=milestone,
            allocated_to_type="country",
            country_id="Uganda",
            allocated_target=Decimal(target),
            allocation_reason="test",
            allocated_by=self.ia.id,
            effective_date=date(2026, 10, 1),
            status=status,
        )

    def _edit_url(self, milestone):
        return f"/strategic-priorities/milestones/{milestone.id}/edit"

    def _remove_url(self, milestone):
        return f"/strategic-priorities/milestones/{milestone.id}/remove"

    def _priority_remove_url(self, priority):
        return f"/strategic-priorities/priorities/{priority.id}/remove"


class EditTargetsTest(PrioritySettingFixture):
    def _edit_payload(self, **overrides):
        payload = {
            "title": "Schools reached (revised)",
            "targetValue": "120",
            "targetUnit": "schools",
            "coreTarget": "50",
            "clientTarget": "70",
            "participantsPerSchool": "3",
            "allocationMethod": "field_cascade",
            "dueDate": "2027-09-30",
        }
        payload.update(overrides)
        return payload

    def test_the_country_director_edits_the_figures_from_the_page(self):
        priority = self._priority()
        milestone = self._milestone(priority)
        self.client.force_login(self.cd)

        response = self.client.post(self._edit_url(milestone), self._edit_payload())

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], f"/strategic-priorities?fy={FY}")
        milestone.refresh_from_db()
        self.assertEqual(milestone.title, "Schools reached (revised)")
        self.assertEqual(milestone.target_value, Decimal("120.00"))
        self.assertEqual(milestone.core_target, Decimal("50.00"))
        self.assertEqual(milestone.client_target, Decimal("70.00"))
        self.assertEqual(milestone.participants_per_school, 3)
        self.assertEqual(milestone.due_date, date(2027, 9, 30))
        self.assertEqual(milestone.version, 2)

        row = AuditLog.objects.get(
            action=MILESTONE_TARGETS_EDITED, subject_id=str(milestone.id)
        )
        self.assertEqual(row.actor_role, "CountryDirector")
        self.assertEqual(row.actor_id, str(self.cd.id))
        self.assertEqual(Decimal(row.payload["before"]["target_value"]), Decimal("100"))
        self.assertEqual(Decimal(row.payload["after"]["target_value"]), Decimal("120"))
        self.assertIn("target_value", row.payload["changed"])
        self.assertEqual(row.payload["version"], 2)

        followed = self.client.get(response["Location"])
        self.assertContains(followed, "targets saved")

    def test_impact_assessment_edits_too(self):
        milestone = self._milestone(self._priority())
        self.client.force_login(self.ia)

        response = self.client.post(
            self._edit_url(milestone), self._edit_payload(targetValue="150")
        )

        self.assertEqual(response.status_code, 302)
        milestone.refresh_from_db()
        self.assertEqual(milestone.target_value, Decimal("150.00"))
        self.assertEqual(
            AuditLog.objects.get(
                action=MILESTONE_TARGETS_EDITED, subject_id=str(milestone.id)
            ).actor_role,
            "ImpactAssessment",
        )

    def test_the_program_lead_is_refused_and_sees_no_control(self):
        """The PL receives the number; they do not set it."""
        priority = self._priority()
        milestone = self._milestone(priority)
        self.client.force_login(self.pl)

        for url in (
            self._edit_url(milestone),
            self._remove_url(milestone),
            self._priority_remove_url(priority),
        ):
            with self.subTest(url=url):
                response = self.client.post(url, self._edit_payload(reason="x"))
                self.assertEqual(response.status_code, 403)
        milestone.refresh_from_db()
        self.assertEqual(milestone.target_value, Decimal("100"))
        self.assertEqual(milestone.version, 1)

        page = self.client.get(f"/strategic-priorities?fy={FY}")
        self.assertEqual(page.status_code, 200)
        body = page.content.decode()
        self.assertFalse(page.context["can_edit"])
        self.assertNotIn('data-milestone-edit="', body)
        self.assertNotIn('data-milestone-edit-panel="', body)
        self.assertNotIn("Edit targets", body)
        self.assertNotIn(f"Remove from FY{FY}", body)
        self.assertNotIn("/remove", body)

    def test_hr_reads_the_page_without_the_controls(self):
        milestone = self._milestone(self._priority())
        self.client.force_login(self.hr)
        self.assertEqual(
            self.client.post(
                self._edit_url(milestone), self._edit_payload()
            ).status_code,
            403,
        )
        page = self.client.get(f"/strategic-priorities?fy={FY}")
        self.assertEqual(page.status_code, 200)
        self.assertNotIn('data-milestone-edit="', page.content.decode())

    def test_an_editor_sees_the_edit_button_and_the_form(self):
        priority = self._priority()
        milestone = self._milestone(priority)
        self.client.force_login(self.cd)

        page = self.client.get(f"/strategic-priorities?fy={FY}")
        body = page.content.decode()
        self.assertTrue(page.context["can_edit"])
        self.assertIn(f'data-milestone-edit="{milestone.id}"', body)
        self.assertIn(f'aria-label="Edit targets for {milestone.title}"', body)
        self.assertIn(f'data-milestone-edit-panel="{milestone.id}"', body)
        self.assertIn(self._edit_url(milestone), body)
        self.assertIn(self._remove_url(milestone), body)
        self.assertIn(self._priority_remove_url(priority), body)
        self.assertIn(f"Remove from FY{FY}", body)
        # A draft priority asks no reason for an edit; the removals always do.
        self.assertNotIn(f'id="edit-reason-{milestone.id}"', body)
        self.assertIn(f'id="confirm-reason-milestone-{milestone.id}"', body)
        self.assertIn(f'id="confirm-reason-priority-{priority.id}"', body)

    def test_unauthenticated_posts_are_sent_to_login(self):
        priority = self._priority()
        milestone = self._milestone(priority)
        for url in (
            self._edit_url(milestone),
            self._remove_url(milestone),
            self._priority_remove_url(priority),
        ):
            with self.subTest(url=url):
                response = self.client.post(url, {"reason": "x"})
                self.assertEqual(response.status_code, 302)
                self.assertTrue(response["Location"].startswith("/login"))

    def test_a_published_figure_needs_a_reason(self):
        priority = self._priority(status="published")
        milestone = self._milestone(priority)
        allocation = self._allocation(milestone)
        self.client.force_login(self.cd)

        refused = self.client.post(
            self._edit_url(milestone), self._edit_payload(), follow=True
        )
        self.assertContains(refused, "say why the figure is changing")
        milestone.refresh_from_db()
        self.assertEqual(milestone.target_value, Decimal("100"))
        self.assertEqual(milestone.version, 1)

        saved = self.client.post(
            self._edit_url(milestone),
            self._edit_payload(reason="Board revised the country plan"),
            follow=True,
        )
        self.assertContains(saved, "targets saved")
        milestone.refresh_from_db()
        self.assertEqual(milestone.target_value, Decimal("120.00"))
        self.assertEqual(milestone.version, 2)
        # The distributed figure is untouched: allocations change only
        # through the amendment workflow.
        allocation.refresh_from_db()
        self.assertEqual(allocation.allocated_target, Decimal("30"))
        self.assertEqual(allocation.status, "approved")
        row = AuditLog.objects.get(
            action=MILESTONE_TARGETS_EDITED, subject_id=str(milestone.id)
        )
        self.assertEqual(row.payload["reason"], "Board revised the country plan")
        self.assertEqual(row.payload["priority_status"], "published")
        self.assertEqual(row.payload["approved_allocations"], 1)

    def test_the_form_asks_the_reason_and_warns_about_allocations_when_published(
        self,
    ):
        priority = self._priority(status="published")
        milestone = self._milestone(priority)
        self._allocation(milestone)
        self._allocation(milestone, status="draft")
        self.client.force_login(self.ia)

        body = self.client.get(f"/strategic-priorities?fy={FY}").content.decode()
        self.assertIn(f'id="edit-reason-{milestone.id}"', body)
        self.assertIn(
            "1 allocation already distributed keep their figures until amended",
            body,
        )

    def test_core_and_client_cannot_exceed_the_target(self):
        milestone = self._milestone(self._priority())
        self.client.force_login(self.cd)

        response = self.client.post(
            self._edit_url(milestone),
            self._edit_payload(targetValue="100", coreTarget="60", clientTarget="50"),
            follow=True,
        )

        self.assertContains(response, "together they cannot exceed it")
        milestone.refresh_from_db()
        self.assertEqual(milestone.core_target, Decimal("40"))
        self.assertEqual(milestone.version, 1)
        self.assertFalse(
            AuditLog.objects.filter(action=MILESTONE_TARGETS_EDITED).exists()
        )

    def test_a_scoreable_milestone_needs_a_positive_target(self):
        milestone = self._milestone(self._priority())
        with self.assertRaises(BadRequest):
            edit_milestone_targets(
                milestone, data={"targetValue": "0"}, principal=self.cd
            )
        with self.assertRaises(BadRequest):
            edit_milestone_targets(
                milestone, data={"targetValue": "ten"}, principal=self.cd
            )
        # Non-scoreable rows may be kept without a figure.
        edit_milestone_targets(
            milestone,
            data={
                "targetValue": "",
                "coreTarget": "",
                "clientTarget": "",
                "allocationMethod": "non_scoreable",
            },
            principal=self.ia,
        )
        milestone.refresh_from_db()
        self.assertIsNone(milestone.target_value)
        self.assertEqual(milestone.allocation_method, "non_scoreable")

    def test_the_service_reads_the_matrix_not_the_role_string(self):
        milestone = self._milestone(self._priority())
        from apps.core.exceptions import Forbidden

        with self.assertRaises(Forbidden):
            edit_milestone_targets(
                milestone, data={"targetValue": "5"}, principal=self.pl
            )


class RemoveMilestoneTest(PrioritySettingFixture):
    def test_a_milestone_with_an_allocation_stays(self):
        milestone = self._milestone(self._priority())
        self._allocation(milestone)
        self.client.force_login(self.cd)

        response = self.client.post(
            self._remove_url(milestone), {"reason": "Not this year"}, follow=True
        )

        self.assertContains(response, "Withdraw them first")
        self.assertTrue(PriorityMilestone.objects.filter(pk=milestone.pk).exists())
        self.assertFalse(AuditLog.objects.filter(action=MILESTONE_REMOVED).exists())

    def test_a_reason_is_required(self):
        milestone = self._milestone(self._priority())
        with self.assertRaises(BadRequest):
            remove_milestone(milestone, principal=self.cd, reason="   ")
        self.assertTrue(PriorityMilestone.objects.filter(pk=milestone.pk).exists())

    def test_a_milestone_nobody_depends_on_leaves_with_a_snapshot(self):
        priority = self._priority()
        milestone = self._milestone(priority)
        milestone_id = str(milestone.id)
        self.client.force_login(self.ia)

        response = self.client.post(
            self._remove_url(milestone),
            {"reason": "Uganda will not run this programme in FY2027"},
            follow=True,
        )

        self.assertContains(response, f"removed from FY{FY}")
        self.assertFalse(PriorityMilestone.objects.filter(pk=milestone_id).exists())
        self.assertTrue(StrategicPriority.objects.filter(pk=priority.pk).exists())
        row = AuditLog.objects.get(action=MILESTONE_REMOVED, subject_id=milestone_id)
        self.assertEqual(row.subject_kind, "PriorityMilestone")
        self.assertEqual(row.actor_role, "ImpactAssessment")
        self.assertEqual(row.payload["code"], "SCHOOLS_REACHED")
        self.assertEqual(row.payload["title"], "Milestone SCHOOLS_REACHED")
        self.assertEqual(row.payload["fy"], FY)
        self.assertEqual(row.payload["level"], "country")
        self.assertEqual(
            Decimal(row.payload["targets"]["target_value"]), Decimal("100")
        )
        self.assertEqual(row.payload["targets"]["target_unit"], "schools")
        self.assertEqual(
            row.payload["reason"], "Uganda will not run this programme in FY2027"
        )


class RemovePriorityTest(PrioritySettingFixture):
    def test_the_group_and_its_milestones_leave_and_are_each_audited(self):
        priority = self._priority()
        first = self._milestone(priority, "FIRST")
        second = self._milestone(priority, "SECOND", target_value=Decimal("7"))
        StrategicPriorityRoleRule.objects.create(
            priority=priority,
            role="CCEO",
            metric_key="setting_test_metric",
            outcome_statement="Reach the schools",
        )
        priority_id = str(priority.id)
        self.client.force_login(self.cd)

        response = self.client.post(
            self._priority_remove_url(priority),
            {"reason": "Not a Uganda focus this FY"},
            follow=True,
        )

        self.assertContains(response, f"removed from FY{FY} with its 2 milestones")
        self.assertFalse(StrategicPriority.objects.filter(pk=priority_id).exists())
        self.assertFalse(
            PriorityMilestone.objects.filter(pk__in=[first.pk, second.pk]).exists()
        )
        self.assertFalse(
            StrategicPriorityRoleRule.objects.filter(priority_id=priority_id).exists()
        )
        # The cycle itself is untouched.
        self.assertTrue(
            StrategicPriorityCycle.objects.filter(pk=self.cycle.pk).exists()
        )

        removed = AuditLog.objects.get(action=PRIORITY_REMOVED, subject_id=priority_id)
        self.assertEqual(removed.subject_kind, "StrategicPriority")
        self.assertEqual(removed.actor_role, "CountryDirector")
        self.assertEqual(removed.payload["code"], "SETTING_TEST_GROUP")
        self.assertEqual(removed.payload["fy"], FY)
        self.assertEqual(
            [m["code"] for m in removed.payload["milestones"]], ["FIRST", "SECOND"]
        )
        self.assertEqual(
            Decimal(removed.payload["milestones"][1]["targets"]["target_value"]),
            Decimal("7"),
        )
        self.assertEqual(removed.payload["role_rules"][0]["role"], "CCEO")
        self.assertEqual(removed.payload["reason"], "Not a Uganda focus this FY")

        per_milestone = AuditLog.objects.filter(
            action=MILESTONE_REMOVED, subject_id__in=[str(first.pk), str(second.pk)]
        )
        self.assertEqual(per_milestone.count(), 2)
        self.assertTrue(
            all(
                row.payload["removed_with_priority"] == priority_id
                for row in per_milestone
            )
        )

    def test_one_distributed_milestone_keeps_the_whole_group(self):
        priority = self._priority()
        free = self._milestone(priority, "FREE")
        held = self._milestone(priority, "HELD")
        self._allocation(held)

        with self.assertRaises(BadRequest) as caught:
            remove_priority(priority, principal=self.ia, reason="Not this FY")

        self.assertIn("Milestone HELD", str(caught.exception.detail))
        self.assertTrue(StrategicPriority.objects.filter(pk=priority.pk).exists())
        self.assertTrue(
            PriorityMilestone.objects.filter(pk__in=[free.pk, held.pk]).count() == 2
        )
        self.assertFalse(AuditLog.objects.filter(action=PRIORITY_REMOVED).exists())
