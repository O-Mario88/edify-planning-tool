"""Partner Monitoring: one Partner's table at a time, in the reader's scope.

Owner, 2026-09-23. The staff-facing place to follow Partner execution:

* each Partner is its own table — never every organisation in one list;
* a CCEO sees their own portfolio, a Programme Lead their team, the country
  roles the country, a Partner user none of it;
* the one-line summary, the filters and the rows are the same records, so the
  numbers reconcile;
* a Partner's hand-back is resolved through one governed decision that never
  moves the school and never makes two of anything;
* staff watch and ask — they do not edit Partner evidence or payment from
  here, and every decision is a drawer, never a form on the page;
* the people who answer for Partner work — Impact Assessment or its monitor —
  Verify & Confirm it or Return it with a reason (owner, 2026-09-26).
"""

from __future__ import annotations

import re
from datetime import date, timedelta

from django.test import Client

from apps.activities.models import Activity
from apps.core.exceptions import BadRequest, Forbidden, NotFoundError
from apps.core.rbac import EdifyRole
from apps.partners.models import PartnerAssignment
from apps.partners.services import resolve_returned_assignment
from apps.partners.support_responsibility import SchoolSupportResponsibilityService
from apps.planning import partner_oversight_service as svc
from apps.planning.test_partner_oversight import PartnerOversightFixture
from apps.schools.models import School


class MonitoringFixture(PartnerOversightFixture):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        from apps.accounts.models import StaffSchoolAssignment

        cls.second_school = School.objects.create(
            school_id="s3",
            name="School B",
            district=cls.district,
            region=cls.region,
            account_owner_id=cls.cceo.id,
        )
        StaffSchoolAssignment.objects.create(
            staff=cls.cceo, school_id=cls.second_school.id
        )
        School.objects.filter(id=cls.school.id).update(account_owner_id=cls.cceo.id)
        School.objects.filter(id=cls.rival_school.id).update(
            account_owner_id=cls.rival_cceo.id
        )

    def at(self, activity, **fields):
        Activity.objects.filter(id=activity.id).update(**fields)
        activity.refresh_from_db()
        return activity

    def ids(self, items):
        return {i.partner_assignment_id for i in items}

    def page(self, user, query=""):
        client = Client()
        client.force_login(user)
        return client.get(f"/partner-oversight/{query}")


class SeparatePartnerTablesTest(MonitoringFixture):
    def test_each_partner_is_its_own_table(self):
        mine = self.assign(partner=self.partner)
        theirs = self.assign(partner=self.other_partner, school=self.second_school)

        first = self.page(self.pl_user, f"?partner={self.partner.id}")
        second = self.page(self.pl_user, f"?partner={self.other_partner.id}")

        for response in (first, second):
            body = response.content.decode()
            self.assertEqual(response.status_code, 200)
            # One Partner's school, cluster and activity tables — never two
            # Partners in one workspace.
            self.assertEqual(body.count("data-partner-monitoring-table"), 3)
            self.assertIn("Partner X", body)
            self.assertIn("Partner Y", body)
        self.assertIn(f'data-assignment="{mine.id}"', first.content.decode())
        self.assertNotIn(f'data-assignment="{theirs.id}"', first.content.decode())
        self.assertIn(f'data-assignment="{theirs.id}"', second.content.decode())
        self.assertNotIn(f'data-assignment="{mine.id}"', second.content.decode())

    def test_the_staff_owner_is_on_every_row(self):
        self.assign()

        body = self.page(self.pl_user).content.decode()

        self.assertIn("Staff member", body)
        self.assertIn("James", body)

    def test_many_partners_get_a_picker_not_an_overflowing_row(self):
        from apps.partners.models import Partner

        for index in range(7):
            partner = Partner.objects.create(name=f"Org {index}", active_status=True)
            school = School.objects.create(
                school_id=f"many-{index}",
                name=f"Many {index}",
                district=self.district,
                region=self.region,
                account_owner_id=self.cceo.id,
            )
            self.assign(partner=partner, school=school)

        body = self.page(self.pl_user).content.decode()

        self.assertIn('aria-label="Choose a Partner"', body)
        self.assertNotIn('aria-label="Partners"', body)


class RoleScopeTest(MonitoringFixture):
    def test_a_cceo_sees_only_their_own_portfolio(self):
        mine = self.assign()
        rival = self.assign(cceo=self.rival_cceo, school=self.rival_school)

        items = svc.build_items(self.cceo_user, fy=self.fy)

        self.assertIn(mine.id, self.ids(items))
        self.assertNotIn(rival.id, self.ids(items))

    def test_a_programme_lead_sees_the_supervised_team(self):
        mine = self.assign()
        rival = self.assign(cceo=self.rival_cceo, school=self.rival_school)

        items = svc.build_items(self.pl_user, fy=self.fy)

        self.assertIn(mine.id, self.ids(items))
        self.assertNotIn(rival.id, self.ids(items))

    def test_country_roles_see_the_country(self):
        mine = self.assign()
        rival = self.assign(cceo=self.rival_cceo, school=self.rival_school)
        for role in (EdifyRole.COUNTRY_DIRECTOR, EdifyRole.IMPACT_ASSESSMENT):
            user = self._staff(f"{role.value}@m.test", role.value, role)[0]
            with self.subTest(role=role.value):
                self.assertEqual(
                    {mine.id, rival.id}, self.ids(svc.build_items(user, fy=self.fy))
                )

    def test_a_partner_user_cannot_open_staff_monitoring(self):
        from apps.accounts.models import User

        officer = User.objects.create(
            email="officer@m.test",
            name="Officer",
            roles=[EdifyRole.PARTNER_FIELD_OFFICER.value],
            active_role=EdifyRole.PARTNER_FIELD_OFFICER.value,
            is_active=True,
        )
        self.assign()

        response = self.page(officer)

        self.assertNotEqual(response.status_code, 200)

    def test_the_export_carries_only_the_readers_scope(self):
        self.assign()
        self.assign(cceo=self.rival_cceo, school=self.rival_school)
        client = Client()
        client.force_login(self.pl_user)

        response = client.get("/partner-oversight/export?fy=" + self.fy)
        self.assertEqual(response.status_code, 200, response.get("Location"))
        body = b"".join(response.streaming_content).decode()

        self.assertIn("School A", body)
        self.assertNotIn("Rival School", body)

    def test_the_export_button_follows_the_export_permission(self):
        """A CCEO monitors their Partners but does not hold data export, so
        the page offers no button the export route would then refuse."""
        self.assign()

        self.assertNotIn(
            "/partner-oversight/export", self.page(self.cceo_user).content.decode()
        )
        self.assertIn(
            "/partner-oversight/export", self.page(self.pl_user).content.decode()
        )


class FiltersAndTotalsTest(MonitoringFixture):
    def setUp(self):
        super().setUp()
        past = date.today() - timedelta(days=3)
        self.scheduled = self.assign()
        self.schedule(self.scheduled)
        self.submitted = self.assign(school=self.second_school)
        self.at(self.schedule(self.submitted), status="awaiting_ia_verification")
        self.returned_by_ia = self.assign()
        self.at(
            self.schedule(self.returned_by_ia),
            status="returned_by_ia",
            ia_verification_status="returned",
        )
        self.verified = self.assign(school=self.second_school)
        self.at(
            self.schedule(self.verified),
            status="ia_verified",
            ia_verification_status="confirmed",
            salesforce_activity_id="SVE-MON-1",
        )
        self.paid = self.assign()
        self.at(
            self.schedule(self.paid),
            status="ia_verified",
            ia_verification_status="confirmed",
            payment_status="paid",
            salesforce_activity_id="SVE-MON-2",
        )
        self.handed_back = self.assign(
            school=self.second_school,
            status="returned_to_staff",
            return_reason_category="capacity",
            return_reason="No facilitator free this term.",
        )
        # The two still waiting come last: a school waits on the same partner
        # once at a time, so they cannot sit open while the others are made.
        self.awaiting = self.assign()
        self.overdue = self.assign(school=self.second_school, scheduled_date=past)
        self.items = svc.build_items(self.pl_user, fy=self.fy)

    def matching(self, key):
        return {i.partner_assignment_id for i in self.items if i.matches(key)}

    def test_each_filter_returns_its_records(self):
        expected = {
            "awaiting_schedule": {self.awaiting.id, self.overdue.id},
            "scheduled": {self.scheduled.id},
            "evidence_submitted": {self.submitted.id},
            "returned_by_ia": {self.returned_by_ia.id},
            "ia_verified": {self.verified.id, self.paid.id},
            "awaiting_payment": {self.verified.id},
            "paid": {self.paid.id},
            "overdue": {self.overdue.id},
            "returned": {self.handed_back.id},
        }
        for key, ids in expected.items():
            with self.subTest(filter=key):
                self.assertEqual(self.matching(key), ids)

    def test_the_summary_reconciles_with_the_rows(self):
        summary = svc.monitoring_summary(self.items)
        counts = svc.filter_counts(self.items)

        self.assertEqual(summary["assigned"], len(self.items))
        self.assertEqual(summary["assigned"], counts["all"])
        self.assertEqual(summary["awaiting_schedule"], counts["awaiting_schedule"])
        self.assertEqual(summary["under_ia_review"], counts["evidence_submitted"])
        self.assertEqual(summary["returned"], counts["returned"])
        self.assertEqual(
            summary["scheduled"], sum(1 for i in self.items if i.is_scheduled)
        )

    def test_ia_salesforce_and_payment_read_as_separate_facts(self):
        by_id = {i.partner_assignment_id: i for i in self.items}

        submitted = by_id[self.submitted.id]
        self.assertEqual(submitted.execution_status, "Evidence Submitted")
        self.assertEqual(submitted.ia_status_label, "Pending")
        self.assertEqual(submitted.salesforce_label, "Pending")
        self.assertEqual(submitted.payment_label, "Not Eligible")

        verified = by_id[self.verified.id]
        self.assertEqual(verified.ia_status_label, "Verified")
        self.assertEqual(verified.salesforce_label, "Confirmed")
        self.assertEqual(verified.payment_label, "Awaiting Payment")
        self.assertEqual(by_id[self.paid.id].payment_label, "Paid")
        self.assertEqual(by_id[self.returned_by_ia.id].ia_status_label, "Returned")

    def test_the_filter_narrows_the_page(self):
        body = self.page(
            self.pl_user, f"?partner={self.partner.id}&status=returned"
        ).content.decode()

        self.assertIn(f'data-assignment="{self.handed_back.id}"', body)
        self.assertNotIn(f'data-assignment="{self.paid.id}"', body)
        self.assertIn("No facilitator free this term.", body)
        self.assertIn("Resolve Exception", body)


class ResolveReturnedWorkTest(MonitoringFixture):
    def setUp(self):
        super().setUp()
        self.handed_back = self.assign(
            status="returned_to_staff",
            return_reason_category="school_unavailable",
            return_reason="School closed for exams.",
        )

    def test_planning_shows_staff_action_required_until_decided(self):
        before = SchoolSupportResponsibilityService.for_school(self.school)
        self.assertTrue(before.staff_action_required)
        self.assertEqual(before.display, "Staff · James")

        resolve_returned_assignment(
            self.handed_back.id, {"resolution": "staff_delivery"}, self.cceo_user
        )

        after = SchoolSupportResponsibilityService.for_school(self.school)
        self.assertFalse(after.staff_action_required)
        self.assertEqual(after.display, "Staff · James")

    def test_reassigning_opens_exactly_one_replacement(self):
        result = resolve_returned_assignment(
            self.handed_back.id,
            {"resolution": "reassigned", "partner_id": self.other_partner.id},
            self.cceo_user,
        )
        again = resolve_returned_assignment(
            self.handed_back.id,
            {"resolution": "reassigned", "partner_id": self.other_partner.id},
            self.cceo_user,
        )

        replacements = PartnerAssignment.objects.filter(
            replaces_assignment=self.handed_back
        )
        self.assertEqual(replacements.count(), 1)
        replacement = replacements.get()
        self.assertEqual(replacement.partner_id, self.other_partner.id)
        self.assertEqual(replacement.school_id, self.school.id)
        self.assertEqual(
            replacement.status, PartnerAssignment.STATUS_PENDING_SCHEDULING
        )
        self.assertIsNone(replacement.scheduled_activity_id)
        self.assertEqual(result["replacementAssignmentId"], replacement.id)
        self.assertEqual(again["replacementAssignmentId"], replacement.id)
        self.assertFalse(Activity.objects.filter(school=self.school).exists())
        self.assertEqual(
            SchoolSupportResponsibilityService.for_school(self.school).display,
            "Partner · Partner Y",
        )

    def test_the_partner_that_returned_it_cannot_be_given_it_back(self):
        with self.assertRaises(BadRequest):
            resolve_returned_assignment(
                self.handed_back.id,
                {"resolution": "reassigned", "partner_id": self.partner.id},
                self.cceo_user,
            )

    def test_another_team_cannot_resolve_it(self):
        with self.assertRaises(NotFoundError):
            resolve_returned_assignment(
                self.handed_back.id,
                {"resolution": "support_closed"},
                self.rival_cceo_user,
            )

    def test_a_role_without_the_grant_cannot_resolve_it(self):
        accountant = self._staff(
            "acc-resolve@m.test", "Books", EdifyRole.PROGRAM_ACCOUNTANT
        )[0]
        with self.assertRaises(Forbidden):
            resolve_returned_assignment(
                self.handed_back.id, {"resolution": "support_closed"}, accountant
            )

    def test_the_to_do_closes_when_the_decision_is_recorded(self):
        from apps.command_center.todo_service import _returned_assignment_todos
        from apps.core.scoping import resolve_user_scope

        scope = resolve_user_scope(self.cceo_user)
        today = date.today()
        todos = _returned_assignment_todos(self.cceo_user, scope, today)
        self.assertEqual(len(todos), 1)
        self.assertIn("/partner-oversight/", todos[0]["action_url"])

        resolve_returned_assignment(
            self.handed_back.id, {"resolution": "support_closed"}, self.cceo_user
        )

        self.assertEqual(_returned_assignment_todos(self.cceo_user, scope, today), [])

    def test_the_drawer_and_the_post_work_over_http(self):
        client = Client()
        client.force_login(self.cceo_user)

        drawer = client.get(
            f"/partner-oversight/resolve?assignment_id={self.handed_back.id}"
        )
        self.assertEqual(drawer.status_code, 200)
        self.assertIn("School closed for exams.", drawer.content.decode())

        response = client.post(
            "/partner-oversight/resolve/submit",
            {"assignment_id": self.handed_back.id, "resolution": "staff_delivery"},
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(response.status_code, 200)
        self.handed_back.refresh_from_db()
        self.assertEqual(self.handed_back.resolution, "staff_delivery")
        self.assertIsNotNone(self.handed_back.resolved_at)


class ProtectedPartnerFieldsTest(MonitoringFixture):
    def setUp(self):
        super().setUp()
        self.assignment = self.assign()
        self.activity = self.at(
            self.schedule(self.assignment), status="awaiting_ia_verification"
        )
        self.client = Client()
        self.client.force_login(self.cceo_user)

    def test_staff_cannot_perform_ia_verification(self):
        response = self.client.post(
            f"/ia/partner-evidence/{self.activity.id}/complete-action",
            {"salesforce_id": "SVE-STAFF-1"},
        )

        self.assertIn(response.status_code, (302, 403, 404))
        self.activity.refresh_from_db()
        self.assertEqual(self.activity.status, "awaiting_ia_verification")
        self.assertNotEqual(self.activity.ia_verification_status, "confirmed")

    def test_staff_cannot_mark_partner_payment_paid(self):
        response = self.client.post(
            "/finance/actions/clear_partner_payment",
            {"activity_id": self.activity.id, "netsuite_id": "NS-1", "amount": "1"},
        )

        self.assertIn(response.status_code, (302, 403, 404))
        self.activity.refresh_from_db()
        self.assertNotEqual(self.activity.payment_status, "paid")

    def test_the_monitoring_page_carries_no_edit_controls(self):
        body = self.client.get(
            "/partner-oversight/", headers={"HX-Request": "true"}
        ).content.decode()

        # The workspace's filters are a GET form; nothing on it writes.
        for forbidden in (
            "hx-post",
            "hx-put",
            "hx-patch",
            "hx-delete",
            'method="post"',
        ):
            with self.subTest(control=forbidden):
                self.assertNotIn(forbidden, body)

    def test_only_its_reviewers_are_offered_verify_and_return(self):
        """The monitor, not a lead who can merely see the work (owner,
        2026-09-12 authority; 2026-09-26 actions), as items of the row's one
        Actions menu."""
        from apps.evidence.models import EvidenceRecord

        EvidenceRecord.objects.create(
            activity=self.activity, kind="visit_form", uri="pm/visit.pdf"
        )
        monitor = self.client.get(
            f"/partner-oversight/?partner={self.partner.id}"
        ).content.decode()
        lead = self.page(self.pl_user, f"?partner={self.partner.id}").content.decode()

        verify = f"/partner-oversight/verify?activity_id={self.activity.id}"
        send_back = f"/partner-oversight/return?activity_id={self.activity.id}"
        for url in (verify, send_back):
            with self.subTest(url=url):
                self.assertIn(url, monitor)
                self.assertNotIn(url, lead)
        self.assertRegex(
            monitor,
            r'role="menuitem"[^>]*hx-get="'
            + re.escape(verify)
            + r'"[^>]*>Verify &amp; Confirm</button>',
        )
        self.assertRegex(
            monitor,
            r'role="menuitem"[^>]*hx-get="'
            + re.escape(send_back)
            + r'"[^>]*>Return</button>',
        )
        # The Salesforce door it replaces is gone from the row.
        self.assertNotIn(f"/activities/{self.activity.id}/salesforce-id", monitor)


class VerifyAndReturnPartnerWorkTest(MonitoringFixture):
    """Owner, 2026-09-26: "Staff (PL and CCEO, IA) action buttons should have
    Verify and Confirm, Return in case they have not uploaded the evidence or
    uploaded the wrong file as evidence ... they should return with a reason."
    """

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.ia_user, cls.ia = cls._staff(
            "ivy@p.test", "Ivy", EdifyRole.IMPACT_ASSESSMENT
        )

    def setUp(self):
        from apps.evidence.models import EvidenceRecord

        super().setUp()
        self.assignment = self.assign()
        self.activity = self.at(
            self.schedule(self.assignment), status="awaiting_ia_verification"
        )
        EvidenceRecord.objects.create(
            activity=self.activity,
            kind="visit_form",
            uri="pm/visit.pdf",
            original_name="visit.pdf",
        )
        self.client = Client()
        self.client.force_login(self.cceo_user)

    def drawer(self, name, user=None):
        client = self.client
        if user is not None:
            client = Client()
            client.force_login(user)
        return client.get(
            f"/partner-oversight/{name}?activity_id={self.activity.id}",
            headers={"HX-Request": "true"},
        )

    def test_the_verify_drawer_shows_the_evidence_and_asks_for_the_salesforce_id(self):
        body = self.drawer("verify").content.decode()
        self.assertIn('hx-post="/partner-oversight/verify/submit"', body)
        self.assertIn("visit.pdf", body)
        self.assertIn('name="salesforce_id"', body)
        self.assertIn("Verify &amp; Confirm", body)

    def test_verify_and_confirm_confirms_the_work(self):
        response = self.client.post(
            "/partner-oversight/verify/submit",
            {"activity_id": self.activity.id, "salesforce_id": "SVE-PM-0001"},
            headers={"HX-Request": "true"},
        )
        self.assertEqual(response.status_code, 200, response.content[:300])
        self.activity.refresh_from_db()
        self.assertEqual(self.activity.status, "ia_verified")
        self.assertEqual(self.activity.salesforce_activity_id, "SVE-PM-0001")

    def test_with_no_evidence_there_is_nothing_to_confirm_only_to_return(self):
        from apps.evidence.models import EvidenceRecord

        EvidenceRecord.objects.filter(activity_id=self.activity.id).delete()
        body = self.drawer("verify").content.decode()
        self.assertIn("data-no-evidence", body)
        self.assertNotIn('type="submit"', body)
        self.assertIn(f"/partner-oversight/return?activity_id={self.activity.id}", body)

    def test_the_return_drawer_offers_the_owners_reasons_first(self):
        body = self.drawer("return").content.decode()
        self.assertIn('hx-post="/partner-oversight/return/submit"', body)
        first = body.index("Evidence not uploaded")
        self.assertLess(first, body.index("Wrong file uploaded as evidence"))
        self.assertLess(
            body.index("Wrong file uploaded as evidence"),
            body.index("Participants not entered in Salesforce"),
        )
        self.assertRegex(body, r'<textarea[^>]*name="comment"[^>]*required')

    def test_return_needs_a_written_reason(self):
        response = self.client.post(
            "/partner-oversight/return/submit",
            {"activity_id": self.activity.id, "reasons": ["Evidence not uploaded"]},
            headers={"HX-Request": "true"},
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("Say why the work is going back", response.content.decode())
        self.activity.refresh_from_db()
        self.assertEqual(self.activity.status, "awaiting_ia_verification")

    def test_the_monitor_returns_it_to_the_partner_with_the_reason(self):
        response = self.client.post(
            "/partner-oversight/return/submit",
            {
                "activity_id": self.activity.id,
                "reasons": ["Wrong file uploaded as evidence", "Not a listed reason"],
                "comment": "The file is last term's visit form.",
            },
            headers={"HX-Request": "true"},
        )
        self.assertEqual(response.status_code, 200, response.content[:300])
        self.activity.refresh_from_db()
        self.assertEqual(self.activity.status, "returned")
        self.assertEqual(self.activity.ia_verification_status, "returned")
        note = self.activity.pl_review_note
        self.assertTrue(note.startswith("Returned by James (CCEO): "), note)
        self.assertIn("Wrong file uploaded as evidence", note)
        self.assertIn("last term's visit form", note)
        self.assertNotIn("Not a listed reason", note)

    def test_impact_assessment_returns_on_its_own_status(self):
        from apps.activities.services import return_partner_work

        return_partner_work(
            self.activity.id,
            {"reasons": ["Evidence not uploaded"], "comment": "Nothing attached."},
            self.ia_user,
        )
        self.activity.refresh_from_db()
        self.assertEqual(self.activity.status, "returned_by_ia")
        self.assertIn("(Impact Assessment)", self.activity.pl_review_note)

    def test_a_lead_who_can_merely_see_it_can_do_neither(self):
        for name in ("verify", "return"):
            with self.subTest(drawer=name):
                self.assertEqual(self.drawer(name, self.pl_user).status_code, 403)
        client = Client()
        client.force_login(self.pl_user)
        response = client.post(
            "/partner-oversight/return/submit",
            {"activity_id": self.activity.id, "comment": "Not mine to return."},
            headers={"HX-Request": "true"},
        )
        self.assertEqual(response.status_code, 403)
        self.activity.refresh_from_db()
        self.assertEqual(self.activity.status, "awaiting_ia_verification")

    def test_work_not_waiting_for_verification_cannot_be_returned(self):
        self.at(self.activity, status="partner_scheduled")
        self.assertEqual(self.drawer("return").status_code, 403)
