"""Cluster Oversight's group training and cluster meeting tables.

Owner, 2026-09-24: both tables read Cluster Name, District, Planned Date,
Executor, Purpose (Meeting Topic), SSA Intervention, Participants, Cost,
Status and Actions. A verified session reads Complete in green. A CCEO's
completion — evidence, attendance and training ID submitted — reads PL Pending
in blue until their Programme Lead clicks Verify, and then Complete. A
Programme Lead's own session is verified by Impact Assessment.
"""

from __future__ import annotations

from datetime import date

from django.test import TestCase

from apps.accounts.models import StaffSupervisorAssignment
from apps.activities.models import Activity, ClusterActivityAttendance
from apps.clusters.models import Cluster
from apps.clusters.oversight_service import cluster_oversight_table_data
from apps.clusters.test_cluster_oversight_views import _create_user
from apps.core.fy import get_operational_fy
from apps.core.rbac import EdifyRole
from apps.geography.models import District, Region
from apps.schools.models import School

COLUMNS = (
    "Cluster Name",
    "District",
    "Planned Date",
    "Executor",
    "Purpose (Meeting Topic)",
    "SSA Intervention",
    "Participants",
    "Cost",
    # Every planned activities table's completion columns (owner, 2026-09-26).
    "Salesforce ID",
    "Evidence",
    "Status",
    "Actions",
)


def _sessions(data) -> dict:
    """Every session row on the page, by activity id, whichever tab holds it."""
    tabs = list(data["cceo_tabs"]) + [
        tab for lead in data["leads"] for tab in lead["cceo_tabs"]
    ]
    return {
        item.activity_id: item
        for tab in tabs
        for item in tab.get("meetings", []) + tab.get("trainings", [])
    }


class ClusterSessionStatusTest(TestCase):
    def setUp(self):
        self.pl = _create_user("lead@status.test", EdifyRole.COUNTRY_PROGRAM_LEAD)
        self.cceo = _create_user("member@status.test", EdifyRole.CCEO)
        self.ia = _create_user("ia@status.test", EdifyRole.IMPACT_ASSESSMENT)
        StaffSupervisorAssignment.objects.create(
            supervisor=self.pl.staff_profile, supervisee=self.cceo.staff_profile
        )
        region = Region.objects.create(name="Status region")
        self.district = District.objects.create(name="Status district", region=region)
        self.cluster = Cluster.objects.create(
            district=self.district,
            region=region,
            name="Status cluster",
            responsible_staff_id=self.cceo.staff_profile.id,
        )
        self.fy = get_operational_fy()
        self.day = date(int(self.fy) - 1, 11, 4)

    def _session(self, kind, status, owner, *, complete=False, **kw):
        """A session; `complete` gives it its TS- Salesforce ID and its
        attendance, which Complete needs besides a verified status (owner,
        2026-09-26)."""
        session = Activity.objects.create(
            activity_type=kind,
            cluster=self.cluster,
            responsible_staff_id=owner.staff_profile.id,
            fy=self.fy,
            planned_date=self.day,
            status=status,
            **kw,
        )
        if complete:
            from apps.evidence.models import EvidenceRecord

            session.salesforce_activity_id = f"TS-{session.id[-10:].upper()}"
            session.save(update_fields=["salesforce_activity_id"])
            EvidenceRecord.objects.create(
                activity=session,
                kind="attendance_form",
                uri="attendance.pdf",
                uploaded_by="u",
            )
        return session

    def _page(self, user):
        self.client.force_login(user)
        response = self.client.get("/cluster-oversight/", {"fy": self.fy})
        self.assertEqual(response.status_code, 200)
        return response

    def test_status_reads_where_the_work_stands(self):
        awaiting_pl = self._session("cluster_meeting", "submitted_to_pl", self.cceo)
        verified = self._session(
            "cluster_training", "ia_verified", self.cceo, complete=True
        )
        # Verified, but neither the Salesforce ID nor the attendance is in.
        unfinished = self._session("cluster_training", "ia_verified", self.cceo)
        awaiting_ia = self._session(
            "cluster_meeting", "awaiting_ia_verification", self.pl
        )
        planned = self._session("cluster_training", "scheduled", self.cceo)
        returned = self._session("cluster_meeting", "returned_by_pl", self.cceo)

        rows = _sessions(cluster_oversight_table_data(self.ia, fy=self.fy))
        expected = {
            awaiting_pl.id: ("PL Pending", "pending"),
            verified.id: ("Complete", "complete"),
            unfinished.id: ("Missing Salesforce ID and evidence", "pending"),
            awaiting_ia.id: ("IA Pending", "pending"),
            planned.id: ("Scheduled", "open"),
            returned.id: ("Returned by PL", "returned"),
        }
        for activity_id, (label, tone) in expected.items():
            with self.subTest(label=label):
                row = rows[activity_id]
                self.assertEqual((row.session_status, row.session_tone), (label, tone))

    def test_both_tables_carry_the_ten_columns(self):
        self._session("cluster_meeting", "scheduled", self.cceo)
        self._session("cluster_training", "scheduled", self.cceo)
        html = self._page(self.pl).content.decode()
        table = html[html.index("data-cluster-sessions") :]
        for column in COLUMNS:
            with self.subTest(column=column):
                self.assertIn(f">{column}</th>", table)
        self.assertEqual(html.count("data-cluster-sessions"), 4)

    def test_the_lead_verifies_a_cceo_completion_and_it_reads_complete(self):
        session = self._session(
            "cluster_training", "submitted_to_pl", self.cceo, complete=True
        )
        confirm = f'action="/pl/review-queue/{session.id}/confirm"'

        response = self._page(self.pl)
        self.assertContains(
            response,
            '<span class="cluster-session-status" data-status-tone="pending">'
            "PL Pending</span>",
        )
        self.assertContains(response, confirm)

        back = f"/cluster-oversight/?fy={self.fy}"
        response = self.client.post(
            f"/pl/review-queue/{session.id}/confirm", {"next": back}
        )
        self.assertRedirects(response, back, fetch_redirect_response=False)
        session.refresh_from_db()
        self.assertEqual(session.status, "ia_verified")

        response = self._page(self.pl)
        self.assertContains(
            response,
            '<span class="cluster-session-status" data-status-tone="complete">'
            "Complete</span>",
        )
        self.assertNotContains(response, confirm)

    def test_impact_assessment_verifies_the_leads_own_session(self):
        own = self._session("cluster_meeting", "awaiting_ia_verification", self.pl)
        cceo_work = self._session("cluster_meeting", "submitted_to_pl", self.cceo)

        response = self._page(self.ia)
        self.assertContains(response, f'href="/ia/verification/{own.id}/"')
        self.assertContains(response, "IA Pending")
        # A CCEO's completion is the Lead's to verify, never IA's.
        self.assertContains(response, "PL Pending")
        self.assertNotContains(response, f"/pl/review-queue/{cceo_work.id}/confirm")

        # The Lead reads their own session as waiting on IA, with nothing to do.
        response = self._page(self.pl)
        self.assertContains(response, "IA Pending")
        self.assertNotContains(response, f"/ia/verification/{own.id}/")
        self.assertNotContains(response, f"/pl/review-queue/{own.id}/confirm")

    def test_only_the_supervising_lead_is_offered_verify(self):
        cd = _create_user("cd@status.test", EdifyRole.COUNTRY_DIRECTOR)
        session = self._session("cluster_meeting", "submitted_to_pl", self.cceo)
        for reader, offered in ((self.pl, True), (self.ia, False), (cd, False)):
            with self.subTest(role=reader.active_role):
                rows = _sessions(cluster_oversight_table_data(reader, fy=self.fy))
                self.assertEqual(rows[session.id].pl_verify, offered)
                self.assertEqual(rows[session.id].ia_verify_url, "")

    def test_participants_are_the_people_the_invited_schools_bring(self):
        schools = [
            School.objects.create(
                name=f"Status school {n}",
                school_id=f"STS-{n}",
                region=self.cluster.region,
                district=self.district,
                cluster_id=str(self.cluster.id),
            )
            for n in range(3)
        ]
        meeting = self._session(
            "cluster_meeting",
            "scheduled",
            self.cceo,
            participants_per_school=4,
            focus_intervention="leadership",
            activity_purpose_text="Termly SSA review",
        )
        for school in schools[:2]:
            ClusterActivityAttendance.objects.create(
                activity=meeting, school=school, invited=True
            )

        row = _sessions(cluster_oversight_table_data(self.pl, fy=self.fy))[meeting.id]
        self.assertEqual(row.participants, 8)
        self.assertEqual(row.topic, "Termly SSA review")
        self.assertEqual(row.intervention_label, "Leadership")
