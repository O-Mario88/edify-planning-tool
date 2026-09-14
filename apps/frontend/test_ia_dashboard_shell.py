"""Impact Assessment's dashboard, queue, To-Dos and notices (IA review, 2026-09-13).

Owner decisions pinned here:
- the dashboard opens on Outcomes, with the work one tab away;
- one fixed header strip that a tab press never changes;
- each view builds only what it renders;
- every count, list and roll-up stops at the verifier's country;
- nobody is offered their own work to verify, and partner work is verified in
  Partner Evidence;
- a headline tile drills into a queue that shows exactly what it counted;
- To-Dos and notices open the record or the queue that resolves them, and the
  Country Director hears every morning about the work only they can verify.
"""

from __future__ import annotations

import re
from datetime import date, timedelta

from django.db import connection
from django.test import TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from apps.accounts.models import StaffProfile, User
from apps.activities.ia_models import DuplicateActivity, VerificationSample
from apps.activities.models import Activity
from apps.core.rbac import EdifyRole
from apps.evidence.models import EvidenceRecord
from apps.geography.models import District, Region
from apps.notifications.models import Notification
from apps.schools.models import School, SSAImportBatch, UnmatchedSSARecord
from apps.ssa.models import SsaRecord

LOCMEM = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "ia-dashboard-shell",
    }
}


def _user(email, name, role, country="Uganda"):
    user = User.objects.create_user(
        email=email,
        name=name,
        roles=[role],
        active_role=role,
        password="x",
        is_active=True,
    )
    StaffProfile.objects.create(user=user, title=role, country=country)
    return user


class IaShellFixture(TestCase):
    @classmethod
    def setUpTestData(cls):
        ug = Region.objects.create(name="Shell Central", country="Uganda")
        ke = Region.objects.create(name="Shell Coast", country="Kenya")
        cls.ug_district = District.objects.create(name="Shell Wakiso", region=ug)
        cls.ke_district = District.objects.create(name="Shell Mombasa", region=ke)
        cls.ug_school = School.objects.create(
            name="Shell Kampala Primary",
            school_id="SH-UG-1",
            region=ug,
            district=cls.ug_district,
        )
        cls.ke_school = School.objects.create(
            name="Shell Mombasa Primary",
            school_id="SH-KE-1",
            region=ke,
            district=cls.ke_district,
        )
        cls.ia = _user("shell-ia@t.org", "Ida Shell", EdifyRole.IMPACT_ASSESSMENT.value)
        cls.ia2 = _user(
            "shell-ia2@t.org", "Ivan Shell", EdifyRole.IMPACT_ASSESSMENT.value
        )
        cls.cd = _user("shell-cd@t.org", "Dan Shell", EdifyRole.COUNTRY_DIRECTOR.value)
        cls.cceo = _user("shell-cceo@t.org", "Cara Shell", EdifyRole.CCEO.value)
        cls.ke_cceo = _user(
            "shell-ke@t.org", "Kip Shell", EdifyRole.CCEO.value, country="Kenya"
        )

        now = timezone.now()
        cls.staff_work = cls._activity(
            cls.ug_school, cls.cceo, "SF-SH-1", submitted=now - timedelta(hours=30)
        )
        cls.fresh_work = cls._activity(
            cls.ug_school, cls.cceo, "SF-SH-2", submitted=now - timedelta(hours=2)
        )
        EvidenceRecord.objects.create(
            activity=cls.fresh_work,
            kind="attendance_form",
            status="uploaded",
            quarantined=False,
            uploaded_by=cls.cceo.id,
        )
        cls.own_work = cls._activity(cls.ug_school, cls.ia, "SF-SH-OWN")
        cls.partner_work = cls._activity(
            cls.ug_school, cls.cceo, "SF-SH-P", delivery_type="partner"
        )
        cls.no_sf_work = cls._activity(cls.ug_school, cls.cceo, "")
        cls.kenya_work = cls._activity(cls.ke_school, cls.ke_cceo, "SF-SH-KE")
        cls.completed_no_sf = cls._activity(
            cls.ug_school, cls.cceo, "", status="completed"
        )
        cls._activity(cls.ke_school, cls.ke_cceo, "", status="completed")
        stale = cls._activity(
            cls.ug_school, cls.cceo, "SF-SH-R", status="returned_by_ia"
        )
        ke_stale = cls._activity(
            cls.ke_school, cls.ke_cceo, "SF-SH-KR", status="returned_by_ia"
        )
        Activity.objects.filter(id__in=[stale.id, ke_stale.id]).update(
            updated_at=now - timedelta(days=10)
        )

        def ssa(school, **kw):
            return SsaRecord.objects.create(
                school=school,
                date_of_ssa=now - timedelta(days=3),
                fy="2026",
                quarter="Q1",
                verification_status="pending",
                uploaded_by=kw.pop("uploaded_by", cls.cceo.id),
                **kw,
            )

        ssa(cls.ug_school, collected_by_user_id=cls.cceo.id)
        ssa(cls.ug_school, collected_by_user_id=cls.ia.id, uploaded_by=cls.ia.id)
        ssa(cls.ke_school, collected_by_user_id=cls.ke_cceo.id)

        ug_batch = SSAImportBatch.objects.create(
            file_name="ug.csv", uploaded_by=cls.ia.id
        )
        ke_batch = SSAImportBatch.objects.create(
            file_name="ke.csv", uploaded_by=cls.ke_cceo.id
        )
        UnmatchedSSARecord.objects.create(batch=ug_batch, school_id="NOPE-UG")
        UnmatchedSSARecord.objects.create(batch=ke_batch, school_id="NOPE-KE")

        DuplicateActivity.objects.create(
            activity=cls.staff_work, duplicate_of=cls.fresh_work, reason="same day"
        )
        DuplicateActivity.objects.create(
            activity=cls.kenya_work, duplicate_of=cls.kenya_work, reason="same day"
        )
        verified = cls._activity(
            cls.ug_school, cls.cceo, "SF-SH-V", status="ia_verified"
        )
        VerificationSample.objects.create(
            activity=verified, original_verifier=cls.ia2.id
        )
        VerificationSample.objects.create(
            activity=verified, original_verifier=cls.ia.id
        )
        ke_verified = cls._activity(
            cls.ke_school, cls.ke_cceo, "SF-SH-KV", status="ia_verified"
        )
        VerificationSample.objects.create(
            activity=ke_verified, original_verifier=cls.ia2.id
        )

    @classmethod
    def _activity(
        cls,
        school,
        responsible,
        code,
        *,
        status="awaiting_ia_verification",
        submitted=None,
        delivery_type="staff",
    ):
        return Activity.objects.create(
            activity_type="school_visit",
            status=status,
            school=school,
            fy="2026",
            planned_date=date(2026, 3, 2),
            responsible_staff_id=responsible.staff_profile.id,
            salesforce_activity_id=code,
            delivery_type=delivery_type,
            submitted_to_ia_at=submitted or timezone.now() - timedelta(hours=1),
        )


def reports_context_for_test(request):
    """Stands in for the impact report lifecycle's dashboard context."""
    return {"ia_report_register": ["from the lifecycle"]}


def _selected_tab(html):
    return re.findall(
        r'id="dashboard-tab-(\w+)"\s+role="tab"\s+aria-selected="true"', html
    )


@override_settings(CACHES=LOCMEM)
class IaDashboardShellTest(IaShellFixture):
    def setUp(self):
        self.client.force_login(self.ia)

    def test_the_dashboard_opens_on_outcomes(self):
        """Owner decision, 2026-09-13: Outcomes is the default, Map a tab."""
        response = self.client.get("/ia/dashboard/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["dashboard_view"], "outcomes")
        self.assertEqual(_selected_tab(response.content.decode()), ["outcomes"])
        self.assertEqual(
            [tab["key"] for tab in response.context["dashboard_tabs"]["tabs"]],
            ["outcomes", "collection", "reports", "map", "operations"],
        )

    def test_retired_static_tabs_fall_back_to_outcomes(self):
        for view in ("framework", "learning"):
            with self.subTest(view=view):
                response = self.client.get("/ia/dashboard/", {"view": view})
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.context["dashboard_view"], "outcomes")
                self.assertNotIn("edify_dashboard_view_ia", response.cookies)
                self.assertNotContains(response, "Manage measurement mappings")

    def test_one_fixed_strip_on_every_view_and_never_in_a_tab_swap(self):
        strips = {}
        for view in ("outcomes", "collection", "reports", "map", "operations"):
            with self.subTest(view=view):
                response = self.client.get("/ia/dashboard/", {"view": view})
                html = response.content.decode()
                self.assertEqual(
                    html.count(
                        '<h2 class="context-metrics__title">Verification workload'
                    ),
                    1,
                )
                self.assertIn('id="ia-mobile-queue-title"', html)
                self.assertIn('href="/ia/dashboard/?view=collection"', html)
                strips[view] = [
                    (item.get("label"), str(item.get("value")))
                    for item in response.context["kpi_strip_items"]
                ]
                swap = self.client.get(
                    "/ia/dashboard/",
                    {"view": view},
                    HTTP_HX_REQUEST="true",
                    HTTP_HX_TARGET="ia-dashboard-view-shell",
                )
                swapped = swap.content.decode()
                self.assertIn("data-dashboard-views", swapped)
                self.assertNotIn("Verification workload", swapped)
                self.assertEqual(_selected_tab(swapped), [view])
        self.assertEqual(len({tuple(s) for s in strips.values()}), 1, strips)

    def test_each_view_builds_only_what_it_renders(self):
        def context(view):
            return self.client.get("/ia/dashboard/", {"view": view}).context

        outcomes = context("outcomes")
        self.assertIn("ia_outcomes", outcomes)
        for key in ("leadership_performance", "district_performance", "exceptions"):
            self.assertNotIn(key, outcomes)
        collection = context("collection")
        self.assertIn("ia_collection", collection)
        self.assertNotIn("leadership_performance", collection)
        reports = context("reports")
        self.assertIn("ia_outcomes", reports)
        self.assertNotIn("district_performance", reports)
        map_view = context("map")
        self.assertIn("district_performance", map_view)
        self.assertNotIn("leadership_performance", map_view)
        self.assertNotIn("ia_outcomes", map_view)
        operations = context("operations")
        self.assertIn("leadership_performance", operations)
        self.assertNotIn("ia_outcomes", operations)
        self.assertNotIn("district_performance", operations)

    def test_the_reports_view_takes_the_report_lifecycles_partial_and_context(self):
        """The Reports view renders the impact report lifecycle's own partial
        and context when they exist, and the draft report until then."""
        from unittest.mock import patch

        with (
            patch(
                "apps.frontend.views.ia_views.IA_REPORTS_CONTEXT_BUILDER",
                "apps.frontend.test_ia_dashboard_shell:reports_context_for_test",
            ),
            patch(
                "apps.frontend.views.ia_views.IA_REPORTS_VIEW_TEMPLATE",
                "partials/ia/outcomes.html",
            ),
        ):
            context = self.client.get("/ia/dashboard/", {"view": "reports"}).context
        self.assertEqual(context["ia_report_register"], ["from the lifecycle"])
        self.assertEqual(context["ia_view_template"], "partials/ia/outcomes.html")
        with patch(
            "apps.frontend.views.ia_views.IA_REPORTS_CONTEXT_BUILDER",
            "apps.impact.no_such_module:builder",
        ):
            response = self.client.get("/ia/dashboard/", {"view": "reports"})
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("ia_report_register", response.context)

    def test_the_strip_counts_only_what_this_verifier_may_verify_here(self):
        kpis = self.client.get("/ia/dashboard/").context["kpis"]
        # Staff work in Uganda with a Salesforce ID, not Ida's own, not the
        # partner's, not Kenya's.
        self.assertEqual(kpis["waiting"], 2)
        self.assertEqual(kpis["overdue"], 1)
        self.assertEqual(kpis["evidence_ready"], 1)
        self.assertEqual(kpis["sf_queue"], 1)
        self.assertEqual(kpis["returned_open"], 1)
        self.assertEqual(kpis["unmatched_ssa"], 1)

    def test_map_and_operations_stop_at_the_border(self):
        map_context = self.client.get("/ia/dashboard/", {"view": "map"}).context
        districts = {row["name"] for row in map_context["district_performance"]}
        self.assertIn("Shell Wakiso", districts)
        self.assertNotIn("Shell Mombasa", districts)
        regions = {row["name"] for row in map_context["region_performance"]}
        self.assertIn("Shell Central", regions)
        self.assertNotIn("Shell Coast", regions)
        response = self.client.get("/ia/dashboard/", {"view": "operations"})
        html = response.content.decode()
        self.assertNotIn("Shell Mombasa Primary", html)
        kpis = response.context["kpis"]
        self.assertEqual(kpis["ssa_pending_review"], 2)
        self.assertEqual(kpis["duplicate_risk"], 1)
        self.assertEqual(
            [q["id"] for q in response.context["queue_items"]],
            [self.staff_work.id, self.fresh_work.id],
        )

    def test_the_verification_quality_tab_stops_at_the_border_too(self):
        self.client.force_login(self.cd)
        response = self.client.get("/analytics/verification-quality")
        self.assertEqual(response.status_code, 200)
        html = response.content.decode()
        self.assertIn("District monitoring", html)
        self.assertNotIn("Shell Mombasa", html)

    def test_other_roles_are_refused(self):
        self.client.force_login(self.cceo)
        response = self.client.get("/ia/dashboard/")
        self.assertEqual(response.status_code, 302)
        response = self.client.get("/ia/verification/")
        self.assertEqual(response.status_code, 302)


@override_settings(CACHES=LOCMEM)
class IaQueueDrilldownTest(IaShellFixture):
    def setUp(self):
        self.client.force_login(self.ia)

    def _ids(self, **params):
        response = self.client.get("/ia/verification/", params)
        self.assertEqual(response.status_code, 200)
        return response, {row["id"] for row in response.context["queue"]}

    def test_the_queue_is_this_verifiers_staff_work_in_their_country(self):
        _response, ids = self._ids()
        self.assertEqual(ids, {self.staff_work.id, self.fresh_work.id})

    def test_each_tile_drills_into_exactly_what_it_counted(self):
        kpis = self.client.get("/ia/dashboard/").context["kpis"]
        items = {
            item["label"]: item
            for item in self.client.get("/ia/dashboard/").context["kpi_strip_items"]
        }
        self.assertTrue(items)
        for params, count_key, expected in (
            ({"age": "overdue"}, "overdue", {self.staff_work.id}),
            ({"evidence": "ready"}, "evidence_ready", {self.fresh_work.id}),
            ({"sf_id": "missing"}, "sf_queue", {self.completed_no_sf.id}),
        ):
            with self.subTest(params=params):
                response, ids = self._ids(**params)
                self.assertEqual(ids, expected)
                self.assertEqual(len(ids), kpis[count_key])
                key, value = next(iter(params.items()))
                chips = response.context["drilldowns"]
                self.assertEqual(
                    [(c["key"], c["value"]) for c in chips], [(key, value)]
                )
                self.assertContains(response, f'data-queue-drilldown="{key}"')
                self.assertContains(response, 'href="/ia/verification/"')
                self.assertContains(
                    response, f'<input type="hidden" name="{key}" value="{value}">'
                )

    def test_a_drilldown_survives_another_filter_and_can_be_removed(self):
        response, ids = self._ids(age="overdue", fy="2026")
        self.assertEqual(ids, {self.staff_work.id})
        chip = response.context["drilldowns"][0]
        self.assertEqual(chip["clear_url"], "/ia/verification/?fy=2026")

    def test_an_unknown_drilldown_value_is_ignored_not_emptying(self):
        _response, ids = self._ids(age="yesterday")
        self.assertEqual(ids, {self.staff_work.id, self.fresh_work.id})

    def test_text_filters_match_names(self):
        _response, ids = self._ids(district="Wakiso")
        self.assertEqual(ids, {self.staff_work.id, self.fresh_work.id})
        _response, ids = self._ids(district="Mombasa")
        self.assertEqual(ids, set())
        _response, ids = self._ids(staff="Cara")
        self.assertEqual(ids, {self.staff_work.id, self.fresh_work.id})

    def test_throughput_headline_reads_the_country(self):
        from apps.activities.models import VerificationHistory

        VerificationHistory.objects.create(
            activity=self.kenya_work,
            verified_by=self.ia2.id,
            verified_at=timezone.now(),
        )
        response = self.client.get("/ia/verification/")
        self.assertEqual(response.context["kpis"]["verified_today"], 0)
        self.assertEqual(response.context["kpis"]["duplicate_risks"], 1)


class IaTodoTest(IaShellFixture):
    def _todos(self, user):
        from apps.command_center.todo_service import get_todos

        return get_todos(user)["todos"]

    def test_verification_rows_are_country_bound_and_never_the_verifiers_own(self):
        from apps.command_center.todo_service import _ia_todos

        rows = {r["id"]: r for r in _ia_todos(self.ia, "ImpactAssessment")}
        self.assertEqual(
            set(rows),
            {
                f"ia-{self.staff_work.id}",
                f"ia-{self.fresh_work.id}",
                f"ia-{self.partner_work.id}",
            },
        )
        self.assertEqual(
            rows[f"ia-{self.staff_work.id}"]["action_url"],
            f"/ia/verification/{self.staff_work.id}/",
        )
        self.assertEqual(rows[f"ia-{self.staff_work.id}"]["status_key"], "overdue")
        self.assertEqual(
            rows[f"ia-{self.partner_work.id}"]["action_url"],
            f"/ia/partner-evidence/{self.partner_work.id}/",
        )
        # A colleague is offered Ida's own work.
        colleague = {r["id"] for r in _ia_todos(self.ia2, "ImpactAssessment")}
        self.assertIn(f"ia-{self.own_work.id}", colleague)
        self.assertEqual(_ia_todos(self.cceo, "CCEO"), [])

    def test_the_desks_other_queues_arrive_as_summary_rows(self):
        from apps.activities.ia_todos import ia_queue_todos

        rows = {
            r["id"]: r
            for r in ia_queue_todos(self.ia, "ImpactAssessment", timezone.localdate())
        }
        self.assertEqual(
            set(rows),
            {
                "ia-ssa-pending",
                "ia-ssa-unmatched",
                "ia-duplicates",
                "ia-samples",
                "ia-returned-stale",
            },
        )
        # Uganda only; Ida's own SSA upload and her own certification excluded.
        self.assertEqual(rows["ia-ssa-pending"]["linked"], "1 waiting")
        self.assertEqual(rows["ia-ssa-pending"]["action_url"], "/ssa/verification/")
        self.assertEqual(rows["ia-ssa-unmatched"]["linked"], "1 waiting")
        self.assertEqual(rows["ia-duplicates"]["linked"], "1 waiting")
        self.assertEqual(rows["ia-samples"]["linked"], "1 waiting")
        self.assertEqual(rows["ia-samples"]["action_url"], "/ia/samples/")
        self.assertEqual(rows["ia-returned-stale"]["linked"], "1 waiting")
        # Ivan certified the other sample, and did not upload the second SSA.
        ivan = {
            r["id"]: r
            for r in ia_queue_todos(self.ia2, "ImpactAssessment", timezone.localdate())
        }
        self.assertEqual(ivan["ia-ssa-pending"]["linked"], "2 waiting")
        self.assertEqual(ivan["ia-samples"]["linked"], "1 waiting")
        for role, user in (("CountryDirector", self.cd), ("CCEO", self.cceo)):
            with self.subTest(role=role):
                self.assertEqual(ia_queue_todos(user, role, timezone.localdate()), [])

    def test_the_rows_reach_the_to_do_queue(self):
        ids = {row["id"] for row in self._todos(self.ia)}
        self.assertIn("ia-ssa-pending", ids)
        self.assertIn(f"ia-{self.staff_work.id}", ids)
        self.assertNotIn(f"ia-{self.own_work.id}", ids)
        self.assertNotIn(f"ia-{self.kenya_work.id}", ids)


class IaNoticeTest(IaShellFixture):
    def test_handoffs_open_the_record_or_its_queue(self):
        from apps.notifications.services import NotificationLinkResolver as R

        cases = (
            (
                ("activity_submitted_for_review", "Activity", "a1"),
                "/ia/verification/a1/",
            ),
            (
                ("activity_submitted_for_verification", "partner_activity", "a2"),
                "/ia/partner-evidence/a2/",
            ),
            (("activity_submitted_for_review", None, None), "/ia/verification/"),
            (("critical_school_ssa", "School", "s1"), "/ssa/verification/"),
            (("evidence_returned", "Activity", "a3"), "/ia/returned/"),
        )
        for (event, kind, ctx), expected in cases:
            with self.subTest(event=event, kind=kind):
                route, _label = R.resolve(event, kind, ctx, "ImpactAssessment")
                self.assertEqual(route, expected)
        # Other roles keep their own routes.
        route, _ = R.resolve("critical_school_ssa", "School", "s1", "CountryDirector")
        self.assertEqual(route, "/analytics/country-director")

    def test_the_country_director_hears_about_ia_officers_own_work(self):
        from apps.realtime.jobs import _do_ia_verification_digest

        created = _do_ia_verification_digest()
        # Ida, Ivan and the Country Director; nobody in Kenya holds IA.
        self.assertEqual(created, 3)
        dan = Notification.objects.get(
            recipient_id=self.cd.id, source_event_type="ia_verification_digest"
        )
        self.assertIn("1 IA officers' submissions waiting for you", dan.title)
        self.assertEqual(dan.target_route, "/ia/verification/")
        ida = Notification.objects.get(
            recipient_id=self.ia.id, source_event_type="ia_verification_digest"
        )
        # Staff 1, fresh 1, partner 1, no-SF staff 1 — Uganda, not her own.
        self.assertIn("4 waiting for verification", ida.title)
        self.assertIn("1 past 24h", ida.title)
        self.assertIn("1 from partners", ida.title)
        self.assertEqual(_do_ia_verification_digest(), 0)

    def test_the_notice_page_lists_the_readers_verification_notices(self):
        Notification.objects.create(
            recipient_id=self.ia.id,
            title="Work submitted for verification",
            body="Shell Kampala Primary is waiting",
            category="verification",
            target_route=f"/ia/verification/{self.staff_work.id}/",
        )
        Notification.objects.create(
            recipient_id=self.ia2.id,
            title="Someone else's notice",
            category="verification",
        )
        self.client.force_login(self.ia)
        response = self.client.get("/ia/notifications/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Shell Kampala Primary is waiting")
        self.assertContains(response, f'href="/ia/verification/{self.staff_work.id}/"')
        self.assertNotContains(response, "Someone else's notice")
        self.client.force_login(self.cceo)
        self.assertEqual(self.client.get("/ia/notifications/").status_code, 302)


@override_settings(CACHES=LOCMEM)
class IaDashboardQueryBudgetTest(IaShellFixture):
    """Per-view ceilings, never targets, and none of them grows with data.

    Measured against a cache this process owns: dev tests share a real Redis
    (performance-pass note)."""

    #: Measured on this fixture (2026-09-14): outcomes 19, collection 19,
    #: reports 19, map 34, operations 49 — before the IA review every view paid
    #: for the whole operations build first (63 queries plus its own). The
    #: headroom on the outcome views leaves room for the portfolio-wide school
    #: change, the collection worklist and the report register those views are
    #: about to read; it is a ceiling, never a target.
    BUDGETS = {
        "outcomes": 30,
        "collection": 34,
        "reports": 30,
        "map": 40,
        "operations": 56,
    }

    def setUp(self):
        self.client.force_login(self.ia)
        self.client.get("/api/health/live")

    def _count(self, view):
        with CaptureQueriesContext(connection) as ctx:
            response = self.client.get("/ia/dashboard/", {"view": view})
        self.assertEqual(response.status_code, 200)
        return len(ctx.captured_queries)

    def test_each_view_stays_inside_its_budget_and_flat_as_data_grows(self):
        for view in self.BUDGETS:
            self._count(view)  # warm per-process caches
        small = {view: self._count(view) for view in self.BUDGETS}
        for i in range(25):
            school = School.objects.create(
                name=f"Shell Grow {i}",
                school_id=f"SH-G-{i}",
                region=self.ug_school.region,
                district=self.ug_district,
            )
            self._activity(school, self.cceo, f"SF-G-{i}")
        large = {view: self._count(view) for view in self.BUDGETS}
        for view, budget in self.BUDGETS.items():
            with self.subTest(view=view):
                self.assertLessEqual(large[view], budget, large)
                self.assertLessEqual(large[view], small[view] + 1, (small, large))

    def test_the_to_do_builders_are_constant_cost(self):
        from apps.activities.ia_todos import ia_queue_todos
        from apps.command_center.todo_service import _ia_todos

        def measure():
            with CaptureQueriesContext(connection) as ctx:
                _ia_todos(self.ia, "ImpactAssessment")
                ia_queue_todos(self.ia, "ImpactAssessment", timezone.localdate())
            return len(ctx.captured_queries)

        measure()
        small = measure()
        for i in range(25):
            self._activity(self.ug_school, self.cceo, f"SF-T-{i}")
        large = measure()
        self.assertLessEqual(large, small)
        # Measured at 10: scope, the waiting rows and five aggregates.
        self.assertLessEqual(large, 12)
