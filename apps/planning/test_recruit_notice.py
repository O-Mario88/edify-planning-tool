"""Somebody who holds too few schools for their visit target is told to recruit.

Owner, 2026-10-07: 280 and 560 are the visits a Programme Lead and a CCEO
plan in a year whatever they hold, "but those with less should be notified to
recruit more schools to meet the target". The Planning Monitor and My Plan
say how many (two visits a Core school, one each of the others), and the
person gets one notice for as long as it is true.
"""

import re

from apps.notifications.models import Notification
from apps.planning import recruit_notice
from apps.planning.recruit_notice import CONTEXT_TYPE, RECRUIT_SCHOOLS_EVENT
from apps.planning.test_monitors_people import FY, PeopleFixture
from apps.schools.models import School


def text(response) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", response.content.decode()))


class WhoIsShortTests(PeopleFixture):
    """Cara holds one Core and one Client school; nobody else holds any."""

    def by_name(self):
        return {p.person.name: p for p in recruit_notice.portfolios()}

    def test_everybody_who_plans_visits_is_read_with_what_they_hold(self):
        people = self.by_name()
        self.assertEqual(len(people), 5)
        cara = people[self.cara_user.name]
        self.assertEqual((cara.core, cara.client), (1, 1))
        # Two visits at the Core school and one at the other, of 560.
        self.assertEqual(cara.schools_to_recruit, 557)
        self.assertEqual(people[self.dan_user.name].schools_to_recruit, 560)
        self.assertEqual(people[self.lead_user.name].schools_to_recruit, 280)
        self.assertNotIn(self.cd_user.name, people)

    def test_a_closed_school_takes_no_visit(self):
        School.objects.filter(pk=self.client_school.pk).update(
            operational_status="permanently_closed"
        )
        self.assertEqual(self.by_name()[self.cara_user.name].schools_to_recruit, 558)


class TheNoticeTests(PeopleFixture):
    def notices(self, user=None):
        found = Notification.objects.filter(source_event_type=RECRUIT_SCHOOLS_EVENT)
        return found.filter(recipient_id=user.id) if user else found

    def give(self, profile, how_many):
        School.objects.bulk_create(
            School(
                school_id=f"RCT-{profile.id}-{n}",
                name=f"Recruited {n}",
                region=self.region,
                district=self.district,
                school_type="client",
                account_owner_id=profile.id,
            )
            for n in range(how_many)
        )

    def test_each_person_who_is_short_gets_one_notice_that_opens_my_plan(self):
        self.assertEqual(recruit_notice.sweep(), 5)
        notice = self.notices(self.cara_user).get()
        self.assertEqual(notice.title, recruit_notice.TITLE)
        self.assertIn("560 visits a year", notice.body)
        self.assertEqual(notice.target_route, "/my-plan")
        self.assertEqual(
            (notice.context_type, notice.context_id), (CONTEXT_TYPE, self.cara.id)
        )
        self.assertIn("280 visits a year", self.notices(self.lead_user).get().body)
        self.assertFalse(self.notices(self.cd_user).exists())

    def test_nobody_is_told_twice_while_it_is_still_true(self):
        recruit_notice.sweep()
        self.assertEqual(recruit_notice.sweep(), 0)
        self.assertEqual(self.notices().count(), 5)
        # Not even somebody who cleared theirs away.
        self.notices(self.dan_user).update(status="archived")
        self.assertEqual(recruit_notice.sweep(), 0)
        self.assertEqual(self.notices(self.dan_user).count(), 1)

    def test_the_notice_closes_when_the_person_holds_enough(self):
        recruit_notice.sweep()
        self.give(self.dan, 560)
        self.assertEqual(recruit_notice.sweep(), 0)
        self.assertIsNotNone(self.notices(self.dan_user).get().resolved_at)
        self.assertIsNone(self.notices(self.cara_user).get().resolved_at)

    def test_somebody_who_falls_short_again_is_told_again(self):
        recruit_notice.sweep()
        self.give(self.dan, 560)
        recruit_notice.sweep()
        School.objects.filter(account_owner_id=self.dan.id).delete()
        self.assertEqual(recruit_notice.sweep(), 1)
        self.assertEqual(self.notices(self.dan_user).count(), 2)

    def test_it_goes_out_with_the_days_plan_notices(self):
        from apps.realtime.jobs import _do_daily_planning_notices

        _do_daily_planning_notices()
        self.assertEqual(self.notices().count(), 5)


class OnThePagesTests(PeopleFixture):
    def test_the_monitor_says_who_must_recruit_and_how_many(self):
        self.client.force_login(self.cd_user)
        for view in ("readiness", "detail"):
            with self.subTest(view=view):
                page = text(self.client.get(f"/planning-monitor/?view={view}&fy={FY}"))
                self.assertIn("recruit 557 more schools", page)
                self.assertIn("recruit 560 more schools", page)
                # The Lead's team: the Lead and two officers, 280 + 557 + 560.
                self.assertIn("3 to recruit 1,397 schools", page)

    def test_planning_detail_reads_everybody_against_the_role_target(self):
        self.client.force_login(self.cd_user)
        response = self.client.get(f"/planning-monitor/?view=detail&fy={FY}")
        officers = {o.name: o for o in response.context["monitor"]["totals"].officers}
        cara, dan = officers[self.cara_user.name], officers[self.dan_user.name]
        for person in (cara, dan):
            self.assertEqual(person.readiness.staff_visits.target, 560)
            self.assertEqual(person.core_visit_target + person.client_visit_target, 560)
        self.assertEqual((cara.core_visit_target, cara.client_visit_target), (2, 558))

    def test_my_plan_tells_the_person(self):
        self.client.force_login(self.cara_user)
        response = self.client.get(f"/my-plan?fy={FY}")
        page = text(response)
        self.assertIn("Your target is 560 visits a year", page)
        self.assertIn(
            "Your schools take 3 of those 560 visits: recruit 557 more schools "
            "to meet your target.",
            page,
        )
        self.assertIn("data-recruit", response.content.decode())
