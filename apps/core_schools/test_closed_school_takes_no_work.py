"""A closed school is kept, hidden from portfolios and takes no work (owner, 2026-09-15).

Closing never deletes the school. It leaves the portfolio lists, every door
that would plan, assign or invite work refuses it, and it moves to the Closed
Schools page, which the CCEO, Programme Lead, IA and CD all reach.

Also here: a Core activity saved from its drawer opens My Plan on the week it
was saved to, not the current week, where it looked unsaved.
"""

from __future__ import annotations

from django.utils import timezone

from apps.core.exceptions import BadRequest
from apps.core.navigation import build_sidebar_for_user
from apps.core.rbac import EdifyRole
from apps.core_schools import test_core_visit_purposes as _purposes
from apps.schools import lifecycle_service
from apps.schools.models import School


def _today():
    """The platform's date, read when a test runs rather than when the module
    is imported. A module-level constant went stale when the suite ran across
    midnight in Africa/Nairobi, and the scheduling rules then refused every
    "today" as a day that had passed."""
    return timezone.localdate()


class ClosedSchoolTakesNoWorkTest(_purposes._CoreFixture):
    def _close(self):
        lifecycle_service.close_school(
            self.school.id,
            {
                "closure_type": "permanent",
                "reason_category": "financial",
                "reason": "The proprietor closed the school at the end of term.",
            },
            self.cceo,
        )
        self.school.refresh_from_db()

    def test_closing_keeps_the_school_and_moves_it_to_the_archive(self):
        self._close()
        self.assertTrue(School.objects.filter(id=self.school.id).exists())
        self.assertIsNone(self.school.deleted_at)
        client = self._client(self.cceo)
        self.assertNotContains(client.get("/core-schools"), "Alpha Core School")
        self.assertContains(client.get("/schools/closed"), "Alpha Core School")
        # Its profile, where the history is read, still opens.
        self.assertEqual(
            client.get(f"/schools/{self.school.school_id}").status_code, 200
        )

    def test_no_drawer_opens_and_nothing_is_scheduled_at_a_closed_school(self):
        self._close()
        client = self._client(self.cceo)
        for url in (
            f"/core-schools/schedule-visit?school_id={self.school.school_id}",
            f"/core-schools/schedule-training?school_id={self.school.school_id}",
            f"/core-schools/assign-partner?school_id={self.school.school_id}",
            f"/planning/schedule-modal?school_id={self.school.school_id}",
        ):
            response = client.get(url, HTTP_HX_REQUEST="true")
            self.assertNotEqual(response.status_code, 200, url)

        response = self._post_visit(purpose_of_visit="ssa_support")
        self.assertNotEqual(response.status_code, 200)
        from apps.activities.models import Activity

        self.assertFalse(Activity.objects.filter(school=self.school).exists())

    def test_the_activity_services_refuse_a_closed_school(self):
        from apps.activities.services import create
        from apps.partners.services import create_assignment

        self._close()
        with self.assertRaisesMessage(BadRequest, "closed"):
            create(
                {
                    "schoolId": self.school.school_id,
                    "activityType": "school_visit",
                    "scheduledDate": _today().isoformat(),
                },
                self.cceo,
            )
        with self.assertRaisesMessage(BadRequest, "closed"):
            create_assignment(school=self.school, partner=self.partner)

    def test_a_closed_school_leaves_its_cluster_membership(self):
        from apps.clusters.services import active_school_count, active_schools

        School.objects.filter(cluster_id=self.cluster.id).update(
            cluster_status="clustered"
        )
        before = active_school_count(self.cluster.id)
        self._close()
        self.assertEqual(active_school_count(self.cluster.id), before - 1)
        self.assertFalse(
            active_schools(self.cluster.id).filter(id=self.school.id).exists()
        )

    def test_closed_schools_is_in_every_oversight_sidebar(self):
        cd, _ = self._staff(
            "cd-closed@core.org", "CD", EdifyRole.COUNTRY_DIRECTOR.value
        )
        for user in (self.cceo, self.pl, self.ia, cd):
            labels = [
                item["label"]
                for section in build_sidebar_for_user(user, "/")
                for item in section["items"]
            ]
            self.assertIn("Closed Schools", labels, user.email)
            self.assertEqual(
                self._client(user).get("/schools/closed").status_code, 200, user.email
            )


class CoreScheduledOpensItsMonthTest(_purposes._CoreFixture):
    def test_a_saved_core_visit_opens_my_plan_on_its_own_month(self):
        """A bare /my-plan looks like a failed save; the saved month does not.

        This pinned the WEEK until 2026-09-17, when My Plan's week view was
        replaced by month-grouped plans filtered on FY, quarter and month.
        A week= link then landed the scheduler on a slice that page can no
        longer show or clear, so the redirect moved up to the month holding
        the activity — still narrow enough that the new row is on screen.
        """
        response = self._post_visit(purpose_of_visit="ssa_support")
        self.assertEqual(response.status_code, 200, response.content[:300])
        self.assertContains(response, f"month={_today().month}")
        self.assertContains(response, "period=month")
        self.assertNotContains(response, "week=")
        self.assertNotContains(response, 'href = "/my-plan";')
