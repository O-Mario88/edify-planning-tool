"""Completion Reviews on the Programme Lead's dashboard, and the evening
reminder to verify (owner, 2026-10-14).

"Completion Reviews page ... is enough just move the page under execution and
completion tab page so the PL can access it from their dashboard direct. The
PL should be alerted at the end of every day to verify cceo work."

Pinned here:

  1. A Programme Lead reads the register on the Execution & Completion tab
     their dashboard carries; the page opened on its own lands there, on the
     officer and completion the link named. Admin keeps the page.
  2. A decision made from the dashboard returns to that tab.
  3. Each evening every lead with completions waiting is told once how many
     and from whom; a lead with none is told nothing, and the notice from the
     day before is closed.
"""

from __future__ import annotations

from datetime import date, timedelta
from urllib.parse import parse_qs, urlparse

from apps.notifications.models import Notification
from apps.pl_review.reminders import (
    VERIFY_REMINDER_EVENT,
    send_verification_reminders,
)
from apps.pl_review.test_completion_reviews import QUEUE_URL, ReviewFixture


class TheRegisterIsOnTheDashboardTabTest(ReviewFixture):
    def test_the_execution_tab_carries_the_register_for_a_lead(self):
        work = self._completion(self.james.id, salesforce_activity_id="SVE-8001")
        response = self.register(self.as_user(self.pl_user))
        self.assertContains(response, "data-review-register")
        self.assertContains(response, "data-completion-reviews-about")
        self.assertContains(response, "The longest waiting comes first.")
        self.assertContains(response, f'data-review-row="{work.id}"')
        self.assertContains(response, f'hx-get="{QUEUE_URL}/{work.id}/drawer"')

    def test_the_country_director_reads_the_tab_without_the_register(self):
        self._completion(self.james.id)
        response = self.as_user(self.cd_user).get(
            "/planning-monitor/", {"view": "execution"}
        )
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "data-review-register")

    def test_the_page_on_its_own_lands_on_the_tab(self):
        work = self._completion(self.james.id)
        response = self.as_user(self.pl_user).get(QUEUE_URL, {"open": work.id})
        self.assertEqual(response.status_code, 302)
        target = urlparse(response.url)
        self.assertEqual(target.path, "/dashboard")
        self.assertEqual(target.fragment, "planning-monitor")
        carried = parse_qs(parse_qs(target.query)["pm"][0])
        self.assertEqual(carried, {"view": ["execution"], "open": [work.id]})

    def test_admin_keeps_the_page(self):
        work = self._completion(self.james.id)
        response = self.as_user(self.admin_user).get(QUEUE_URL)
        self.assertTemplateUsed(response, "pages/my_plan/pl_queue.html")
        self.assertContains(response, f'data-review-row="{work.id}"')

    def test_a_decision_from_the_dashboard_returns_to_the_tab(self):
        work = self._completion(self.james.id, salesforce_activity_id="SVE-8002")
        client = self.as_user(self.pl_user)
        for drawer in ("drawer", "return-drawer"):
            with self.subTest(drawer=drawer):
                response = client.get(
                    f"{QUEUE_URL}/{work.id}/{drawer}",
                    headers={
                        "HX-Request": "true",
                        "HX-Current-URL": "http://testserver/dashboard?fy=2027",
                    },
                )
                self.assertContains(
                    response, 'name="next" value="/dashboard?pm=view%3Dexecution'
                )
        response = client.post(
            f"{QUEUE_URL}/{work.id}/confirm",
            {"next": "/dashboard?pm=view%3Dexecution#planning-monitor"},
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            response.url, "/dashboard?pm=view%3Dexecution#planning-monitor"
        )
        work.refresh_from_db()
        self.assertEqual(work.status, "ia_verified")

    def test_the_leads_sidebar_no_longer_lists_the_page(self):
        response = self.as_user(self.pl_user).get("/dashboard")
        self.assertNotContains(response, 'href="/pl/review-queue"')


class TheEveningReminderTest(ReviewFixture):
    def _notices(self, user):
        return Notification.objects.filter(
            recipient_id=user.id, source_event_type=VERIFY_REMINDER_EVENT
        )

    def test_each_lead_with_work_waiting_is_told_once(self):
        self._completion(self.james.id)
        self._completion(self.james.id)
        self._completion(self.mary.id, school=self.mary_school)
        today = date(2026, 10, 14)

        self.assertEqual(send_verification_reminders(today), 1)
        notice = self._notices(self.pl_user).get()
        self.assertEqual(
            notice.title, "Verify 3 completed activities before the day ends"
        )
        self.assertIn("2 from James, 1 from Mary", notice.body)
        self.assertEqual(notice.target_route, "/pl/review-queue")
        # The rival lead has nothing waiting and is told nothing.
        self.assertFalse(self._notices(self.rival_pl_user).exists())
        # A re-run the same evening says nothing twice.
        self.assertEqual(send_verification_reminders(today), 0)
        self.assertEqual(self._notices(self.pl_user).count(), 1)

    def test_the_next_evening_replaces_the_notice_and_an_empty_queue_closes_it(self):
        work = self._completion(self.james.id)
        first = date(2026, 10, 14)
        send_verification_reminders(first)
        send_verification_reminders(first + timedelta(days=1))
        open_notices = self._notices(self.pl_user).filter(resolved_at__isnull=True)
        self.assertEqual(
            list(open_notices.values_list("context_id", flat=True)),
            ["verify-2026-10-15"],
        )

        work.status = "ia_verified"
        work.save(update_fields=["status"])
        self.assertEqual(send_verification_reminders(first + timedelta(days=2)), 0)
        self.assertFalse(open_notices.exists())

    def test_the_job_is_scheduled_for_the_end_of_the_day(self):
        from apps.realtime.registry import JOB_REGISTRY

        spec = next(s for s in JOB_REGISTRY if s.name == "verification_reminders")
        self.assertEqual(spec.cron_kwargs, {"hour": 17, "minute": 0})
