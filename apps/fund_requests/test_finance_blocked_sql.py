"""The Finance Blocked page decides "blocked" in SQL and pages it (PERF-06).

It loaded every activity in the country, with budget lines and school, to test
four rules in Python and draw ten rows: 14-18 s for the Accountant at 50,000
schools. The rules are now one WHERE clause; this pins that clause to
`FinanceBlockedReasonService.get_blocked_reasons`, the rule the rest of the
finance chain uses, on every branch.
"""

from __future__ import annotations

from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext

from apps.accounts.models import StaffProfile
from apps.activities.models import Activity, ActivityScheduleCostLine
from apps.evidence.models import EvidenceRecord
from apps.fund_requests.finance_services import FinanceBlockedReasonService
from apps.geography.models import District, Region
from apps.schools.models import School


class FinanceBlockedSqlTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user(
            email="fin-blocked@edify.test",
            password="password123",
            name="Finance Blocked",
            roles=["Admin"],
            active_role="Admin",
            is_active=True,
        )
        StaffProfile.objects.create(id="fin-blocked-staff", user=cls.user)
        region = Region.objects.create(name="Fin Blocked Region")
        district = District.objects.create(name="Fin Blocked District", region=region)
        cls.school = School.objects.create(
            school_id="FIN-BLOCKED-1",
            name="Fin Blocked School",
            region=region,
            district=district,
        )

    def _activity(self, *, evidence=False, budget=False, **fields):
        # Salesforce ids are unique across activities; number each "SF-OK".
        if fields.get("salesforce_activity_id") == "SF-OK":
            self._sf = getattr(self, "_sf", 0) + 1
            fields["salesforce_activity_id"] = f"SF-OK-{self._sf}"
        activity = Activity.objects.create(
            school=self.school,
            activity_type=fields.pop("activity_type", "school_visit"),
            status=fields.pop("status", "ia_verified"),
            responsible_staff_id="fin-blocked-staff",
            **fields,
        )
        if evidence:
            EvidenceRecord.objects.create(
                activity=activity, kind="visit_form", uri="e.pdf", uploaded_by="x"
            )
        if budget:
            ActivityScheduleCostLine.objects.create(
                activity=activity,
                cost_setting_key="transport",
                label="Transport",
                unit_cost=1,
                quantity=1,
                amount=1,
            )
        return activity

    def _scenarios(self):
        clean = dict(evidence=True, budget=True, salesforce_activity_id="SF-OK")
        return [
            self._activity(**clean),  # not blocked
            self._activity(**{**clean, "status": "scheduled"}),
            self._activity(**{**clean, "status": "closed"}),
            self._activity(**{**clean, "status": "accountant_confirmed"}),
            self._activity(**{**clean, "evidence": False}),
            self._activity(**{**clean, "budget": False}),
            self._activity(**{**clean, "salesforce_activity_id": None}),
            self._activity(**{**clean, "salesforce_activity_id": ""}),
            # No Salesforce record for SSA data gathering: no SF ID needed.
            self._activity(
                **{
                    **clean,
                    "salesforce_activity_id": None,
                    "salesforce_record_type_snapshot": "SSA_DATA_GATHERING",
                }
            ),
            self._activity(
                **{
                    **clean,
                    "salesforce_activity_id": "",
                    "salesforce_record_type_snapshot": "none",
                }
            ),
            self._activity(
                **{
                    **clean,
                    "salesforce_activity_id": None,
                    "salesforce_record_type_snapshot": "TRAINING",
                }
            ),
            self._activity(
                evidence=False,
                budget=False,
                status="planned",
                activity_type="cluster_training",
            ),
        ]

    def test_the_sql_filter_agrees_with_the_python_rules_on_every_branch(self):
        scenarios = self._scenarios()
        flagged = set(
            FinanceBlockedReasonService.blocked_activities().values_list(
                "id", flat=True
            )
        )
        for activity in scenarios:
            with self.subTest(activity=activity.pk):
                reasons = FinanceBlockedReasonService.get_blocked_reasons(activity)
                self.assertEqual(activity.pk in flagged, bool(reasons))
        annotated = FinanceBlockedReasonService.blocked_activities()
        for activity in annotated:
            self.assertEqual(
                FinanceBlockedReasonService.get_blocked_reasons(
                    activity,
                    has_evidence=activity.fin_has_evidence,
                    has_budget_lines=activity.fin_has_budget_lines,
                ),
                FinanceBlockedReasonService.get_blocked_reasons(
                    Activity.objects.get(pk=activity.pk)
                ),
            )

    def test_the_page_draws_the_blocked_rows_with_their_reasons(self):
        self._scenarios()
        self.client.force_login(self.user)
        response = self.client.get("/accounts/blocked")
        self.assertEqual(response.status_code, 200)
        page = response.context["blocked"]
        # Seven of the twelve scenarios are blocked (see _scenarios).
        self.assertEqual(len(page), 7)
        self.assertContains(response, "Evidence Missing")
        self.assertContains(response, "Budget Line Missing")

    def test_the_page_costs_the_same_at_any_size(self):
        self.client.force_login(self.user)
        for _ in range(3):
            self._activity(status="scheduled")
        self.client.get("/accounts/blocked")
        with CaptureQueriesContext(connection) as small:
            self.client.get("/accounts/blocked")
        for _ in range(30):
            self._activity(status="scheduled", evidence=True, budget=True)
        with CaptureQueriesContext(connection) as large:
            response = self.client.get("/accounts/blocked")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(large), len(small))
