"""The planning rulebook (owner, 2026-10-01) as tests.

Who plans (a role held, not the role in use), which visits count and for
whom, what each school type needs, when Partner work is planned, and what
a duplicate is.
"""

from __future__ import annotations

from apps.activities.models import Activity
from apps.core.enums import ActivityType, ExecutorType
from apps.core.rbac import EdifyRole
from apps.geography.models import Region
from apps.planning.country_oversight import people, rules
from apps.planning.country_oversight import service as svc
from apps.planning.test_country_planning_oversight import FY, World, day
from apps.schools.models import School

PURPOSES = (
    None,
    "ssa_support",
    "in_school_training",
    "in_school_coaching",
    "training_follow_up",
    "donor_visit",
    "story_gathering",
    "school_invitation",
    "social_visit",
    rules.COMPANION_PURPOSE,
)


class RulebookDefinitionsTest(World):
    def test_rulebook_names_only_real_types(self):
        rules.check()

    def test_database_and_python_agree_on_which_visits_count(self):
        school = self.school("client", self.cceo)
        Activity.objects.bulk_create(
            Activity(
                activity_type=activity_type,
                purpose_type=purpose,
                school=school,
                fy=FY,
                quarter="Q1",
                planned_date=day(30),
                status="scheduled",
            )
            for activity_type in ActivityType.values
            for purpose in PURPOSES
        )
        rows = Activity.objects.filter(school=school)
        counted = dict(
            rows.filter(rules.counted_visit_q())
            .annotate(kind=rules.visit_kind_case())
            .values_list("id", "kind")
        )
        outreach = set(
            rows.filter(rules.outreach_visit_q()).values_list("id", flat=True)
        )
        for pk, activity_type, purpose in rows.values_list(
            "id", "activity_type", "purpose_type"
        ):
            with self.subTest(activity_type=activity_type, purpose=purpose):
                # The rows are staff's: SSA Support counts for them.
                self.assertEqual(
                    counted.get(pk),
                    rules.visit_kind(activity_type, purpose, delivery_type="staff"),
                )
                # A visit is counted or it is outreach, never both.
                self.assertFalse(pk in counted and pk in outreach)

    def test_the_two_kinds_and_staff_ssa_support(self):
        # Owner, 2026-10-03: "Only Follow up, In-school training and SSA
        # Support scheduled by staff not partner ... if it is assigned to the
        # partner it does not count." A day earlier data collection counted
        # nowhere; it still does not for a Partner, or for a shape whose
        # deliverer is not known (asserted below).
        self.assertEqual(
            rules.KIND_ORDER,
            (rules.KIND_FOLLOW_UP, rules.KIND_IN_SCHOOL, rules.KIND_SSA),
        )
        for activity_type, purpose in (
            ("school_visit_ssa_collection", "ssa_support"),
            ("baseline_ssa_visit", None),
            ("core_visit", "ssa_support"),
        ):
            with self.subTest(activity_type=activity_type, by="staff"):
                self.assertEqual(
                    rules.visit_kind(activity_type, purpose, delivery_type="staff"),
                    rules.KIND_SSA,
                )
                self.assertIsNone(
                    rules.visit_kind(activity_type, purpose, delivery_type="partner")
                )
                self.assertFalse(
                    rules.is_uncounted_visit(
                        activity_type, purpose, delivery_type="staff"
                    )
                )
                self.assertTrue(
                    rules.is_uncounted_visit(
                        activity_type, purpose, delivery_type="partner"
                    )
                )
        self.assertEqual(
            rules.visit_kind("in_school_training", "in_school_training"),
            rules.KIND_IN_SCHOOL,
        )
        self.assertEqual(
            rules.visit_kind("training_follow_up_visit", "training_follow_up"),
            rules.KIND_FOLLOW_UP,
        )
        # A Core visit is what its purpose says it is.
        self.assertEqual(
            rules.visit_kind("core_visit", "training_follow_up"), rules.KIND_FOLLOW_UP
        )
        for activity_type, purpose in (
            # Data collection, by its type or by the purpose chosen.
            ("school_visit_ssa_collection", "ssa_support"),
            ("baseline_ssa_visit", None),
            ("partner_ssa_collection", None),
            ("ssa_activity", None),
            ("core_assessment_visit", None),
            ("core_visit", "ssa_support"),
            ("donor_visit", "donor_visit"),
            ("story_gathering_visit", "story_gathering"),
            ("school_invitation", "school_invitation"),
            ("social_visit", "social_visit"),
            ("core_visit", "donor_visit"),
            ("school_visit", rules.COMPANION_PURPOSE),
            ("cluster_meeting", None),
            ("training", None),
        ):
            with self.subTest(activity_type=activity_type):
                self.assertIsNone(rules.visit_kind(activity_type, purpose))

    def test_what_each_school_type_needs(self):
        core = rules.requirement_for("core")
        self.assertEqual((core.staff_visits, core.partner_visits), (2, 2))
        self.assertEqual((core.staff_trainings, core.partner_trainings), (2, 2))
        # "core trained, core graduate and client schools should be treated
        # the same" (owner, 2026-10-02).
        for school_type in ("client", "core_trained", "core_graduate"):
            need = rules.requirement_for(school_type)
            self.assertEqual((need.visits, need.trainings), (1, 1))
        champion = rules.requirement_for("champion")
        self.assertEqual((champion.visits, champion.trainings), (0, 0))
        # 2 visits per Core school and 1 per client-rule school.
        self.assertEqual(
            rules.portfolio_reach({"core": 80, "client": 100, "core_trained": 20}),
            280,
        )

    def test_a_date_is_the_partners_only_when_the_partner_set_it(self):
        self.assertEqual(rules.date_author(self.partner_admin()), "partner")
        # Staff putting the first date on Partner work make it a staff date.
        self.assertEqual(rules.date_author(self.cceo_user), "staff")
        # Staff moving a date the Partner chose leave it the Partner's plan,
        # and an older row nobody recorded stays unrecorded.
        self.assertEqual(rules.date_author(self.cceo_user, "partner"), "partner")
        self.assertEqual(rules.date_author(self.cceo_user, "", already_dated=True), "")

    def partner_admin(self):
        from apps.accounts.models import User

        return User.objects.create(
            email="rule-partner@cpo.test",
            name="Partner Admin",
            roles=[EdifyRole.PARTNER_ADMIN.value],
            active_role=EdifyRole.PARTNER_ADMIN.value,
            is_active=True,
        )


class RosterTest(World):
    def test_every_lead_with_their_cceos_and_targets(self):
        teams = {team.name: team for team in rules.roster("Uganda")}
        self.assertEqual(
            [p.name for p in teams["Lead A"].people],
            ["Lead A", "Officer One", "Officer Two"],
        )
        self.assertEqual(teams["Lead A"].target, 280 + 560 + 560)
        self.assertEqual(teams["Lead B"].target, 280 + 560)

    def test_a_lead_using_another_role_today_is_still_a_lead(self):
        self.pl_user.roles = [
            EdifyRole.COUNTRY_PROGRAM_LEAD.value,
            EdifyRole.ADMIN.value,
        ]
        self.pl_user.active_role = EdifyRole.ADMIN.value
        self.pl_user.save()
        teams = {team.name: team for team in rules.roster("Uganda")}
        lead = teams["Lead A"].people[0]
        self.assertTrue(lead.is_lead)
        self.assertEqual(lead.role_in_use, EdifyRole.ADMIN.value)
        # Their CCEOs stay under them rather than falling to "No Programme Lead".
        self.assertEqual(len(teams["Lead A"].people), 3)
        self.assertNotIn(rules.NO_LEAD_LABEL, teams)

    def test_a_cceo_with_no_lead_is_still_followed(self):
        _user, loose = self.person("cpo-loose", "Officer Loose", EdifyRole.CCEO)
        teams = {team.key: team for team in rules.roster("Uganda")}
        self.assertEqual(
            [p.key for p in teams[rules.NO_LEAD_KEY].people], [str(loose.id)]
        )

    def test_somebody_who_has_left_is_not_on_the_roster(self):
        self.cceo2_user.is_active = False
        self.cceo2_user.save()
        names = [p.name for team in rules.roster("Uganda") for p in team.people]
        self.assertNotIn("Officer Two", names)


class PeoplePlanTest(World):
    def plan(self):
        return people.people_plan(self.cd_user, FY)

    def row(self, plan, profile):
        return next(p for p in plan.people if p.key == str(profile.id))

    def test_expected_is_headcount_times_the_role_target(self):
        plan = self.plan()
        self.assertEqual(plan.headcount(rules.CCEO_ROLE), 3)
        self.assertEqual(plan.headcount(rules.PROGRAM_LEAD_ROLE), 2)
        self.assertEqual(plan.total("target"), 3 * 560 + 2 * 280)

    def test_a_visit_counts_for_whoever_planned_it(self):
        school = self.school("client", self.cceo)
        other = self.school("client", self.cceo)
        self.activity(school, "training_follow_up_visit", owner=self.cceo2)
        self.activity(other, "school_visit_ssa_collection", owner=self.pl)
        plan = self.plan()
        holder = self.row(plan, self.cceo)
        self.assertEqual(holder.visits_planned, 0)
        self.assertEqual(holder.schools, {"client": 2})
        self.assertEqual(self.row(plan, self.cceo2).visits_planned, 1)
        # The Lead's own SSA Support visit is one of the Lead's 280 (owner,
        # 2026-10-03: it counts when staff schedule it).
        lead = self.row(plan, self.pl)
        self.assertEqual(lead.visits_planned, 1)
        self.assertEqual(lead.outreach, 0)
        self.assertEqual(lead.target, 280)

    def test_an_id_from_either_id_space_is_the_same_person(self):
        school = self.school("client", self.cceo)
        visit = self.activity(school, "school_visit")
        # Some paths write the User id where others write the StaffProfile id.
        Activity.objects.filter(pk=visit.pk).update(
            responsible_staff_id=self.cceo_user.id
        )
        self.assertEqual(self.row(self.plan(), self.cceo).visits_planned, 1)

    def test_outreach_is_shown_and_not_counted(self):
        school = self.school("client", self.cceo)
        self.activity(school, "donor_visit", owner=self.cceo)
        self.activity(school, "story_gathering_visit", owner=self.cceo)
        self.activity(
            school, "school_visit", owner=self.cceo, purpose_type="social_visit"
        )
        officer = self.row(self.plan(), self.cceo)
        self.assertEqual(officer.visits_planned, 0)
        self.assertEqual(officer.outreach, 3)

    def test_an_in_school_training_is_one_visit_and_one_training(self):
        school = self.school("client", self.cceo)
        self.activity(
            school,
            "in_school_training",
            owner=self.cceo,
            purpose_type="in_school_training",
        )
        self.activity(
            school,
            "school_visit",
            owner=self.cceo,
            purpose_type=rules.COMPANION_PURPOSE,
        )
        officer = self.row(self.plan(), self.cceo)
        self.assertEqual(officer.visits, {**officer.visits, rules.KIND_IN_SCHOOL: 1})
        self.assertEqual(officer.visits_planned, 1)
        self.assertEqual(officer.trainings, 1)

    def test_undated_cancelled_and_partner_work_is_not_a_staff_plan(self):
        school = self.school("client", self.cceo)
        self.activity(
            school, "school_visit", owner=self.cceo, on=None, status="planned"
        )
        self.activity(school, "school_visit", owner=self.cceo, status="cancelled")
        self.activity(school, "school_visit", owner=self.cceo, partner=self.partner)
        self.assertEqual(self.row(self.plan(), self.cceo).visits_planned, 0)

    def test_a_person_short_of_schools_keeps_the_whole_target(self):
        for _ in range(3):
            self.school("core", self.cceo)
        self.school("client", self.cceo)
        officer = self.row(self.plan(), self.cceo)
        self.assertEqual(officer.reach, 3 * 2 + 1)
        self.assertEqual(officer.target, 560)
        self.assertEqual(officer.shortfall, 560 - 7)

    def test_someone_else_who_planned_a_visit_shows_without_a_target(self):
        school = self.school("client", self.cceo)
        self.activity(school, "school_visit", owner=self.admin)
        plan = self.plan()
        other = self.row(plan, self.admin)
        self.assertEqual((other.role, other.target, other.visits_planned), ("", 0, 1))
        self.assertEqual(other.team_key, people.OTHER_TEAM_KEY)
        self.assertEqual(plan.total("target"), 3 * 560 + 2 * 280)

    def test_partner_planning_is_nothing_until_a_partner_sets_a_date(self):
        waiting = self.school("client", self.cceo)
        moved = self.school("client", self.cceo)
        agency = self.school("client", self.cceo)
        self.handover(
            waiting,
            self.partner,
            status="pending_scheduling",
            assigning_staff_id=self.cceo.id,
        )
        self.activity(
            moved,
            "school_visit",
            partner=self.partner,
            on=None,
            status="assigned_to_partner",
            monitored_by_staff_id=self.cceo.id,
        )
        # Staff booked a certified agency onto a day: assigned, not planned.
        self.activity(
            agency,
            "school_visit",
            partner=self.partner2,
            status="partner_scheduled",
            monitored_by_staff_id=self.cceo.id,
            executor_type=ExecutorType.CERTIFIED_PARTNER_AGENCY.value,
            partner_date_set_by="staff",
        )
        officer = self.row(self.plan(), self.cceo)
        self.assertEqual(officer.partner_schools, 3)
        self.assertEqual(officer.partner_assigned, 3)
        self.assertEqual(officer.partner_planned, 0)

        Activity.objects.filter(school=moved).update(
            status="partner_scheduled",
            planned_date=day(50),
            partner_date_set_by="partner",
        )
        officer = self.row(self.plan(), self.cceo)
        self.assertEqual((officer.partner_assigned, officer.partner_planned), (3, 1))

    def test_partner_work_dated_before_the_author_was_kept_is_the_partners(self):
        school = self.school("client", self.cceo)
        self.activity(
            school,
            "school_visit",
            partner=self.partner,
            status="partner_scheduled",
            monitored_by_staff_id=self.cceo.id,
        )
        self.assertEqual(self.row(self.plan(), self.cceo).partner_planned, 1)

    def test_a_dated_hand_over_is_counted_once_as_its_activity(self):
        school = self.school("client", self.cceo)
        visit = self.activity(
            school,
            "school_visit",
            partner=self.partner,
            status="partner_scheduled",
            partner_date_set_by="partner",
        )
        self.handover(
            school,
            self.partner,
            status="partner_scheduled",
            assigning_staff_id=self.cceo.id,
            scheduled_activity=visit,
        )
        officer = self.row(self.plan(), self.cceo)
        self.assertEqual((officer.partner_assigned, officer.partner_planned), (1, 1))
        self.assertEqual(officer.partner_schools, 1)

    def test_trainings_and_cluster_meetings_follow_their_planner(self):
        school = self.school("client", self.cceo, cluster=self.cluster)
        self.session("cluster_meeting", [school])
        self.session("cluster_training", [school])
        officer = self.row(self.plan(), self.cceo)
        self.assertEqual((officer.meetings, officer.cluster_trainings), (1, 1))


class SchoolYearTest(World):
    def year(self):
        return people.school_year(self.cd_user, FY)

    def types(self):
        return {row.school_type: row for row in people.summarise_by_type(self.year())}

    def test_types_are_read_apart_and_champions_need_nothing(self):
        self.school("core", self.cceo)
        self.school("client", self.cceo)
        self.school("core_trained", self.cceo)
        self.school("core_graduate", self.cceo)
        self.school("champion", self.cceo)
        types = self.types()
        self.assertEqual(
            {
                t: (row.schools, row.visit_slots, row.training_slots)
                for t, row in types.items()
            },
            {
                "core": (1, 4, 4),
                "client": (1, 1, 1),
                "core_trained": (1, 1, 1),
                "core_graduate": (1, 1, 1),
                "champion": (1, 0, 0),
            },
        )

    def test_a_slot_is_filled_once_however_many_plans_land_on_it(self):
        core = self.school("core", self.cceo)
        for offset in (10, 20, 30):
            self.activity(core, "core_visit", owner=self.cceo, on=offset)
        for offset in (40, 50, 60):
            self.activity(
                core,
                "core_visit",
                partner=self.partner,
                on=offset,
                status="partner_scheduled",
                partner_date_set_by="partner",
            )
        row = self.types()["core"]
        self.assertEqual((row.staff_slots, row.partner_slots), (2, 2))
        self.assertEqual(row.schools_with_visit, 1)

    def test_a_client_schools_one_slot_is_staffs_when_staff_planned_it(self):
        school = self.school("client", self.cceo)
        self.activity(school, "training_follow_up_visit", owner=self.cceo)
        self.activity(
            school,
            "school_visit",
            partner=self.partner,
            status="partner_scheduled",
            partner_date_set_by="partner",
        )
        row = self.types()["client"]
        self.assertEqual((row.staff_slots, row.partner_slots), (1, 0))
        self.assertEqual(row.with_partner, 1)
        self.assertEqual(row.duplicates, 1)

    def test_a_school_assigned_and_not_dated_is_held_and_not_planned(self):
        school = self.school("client", self.cceo)
        self.handover(school, self.partner, status="pending_scheduling")
        row = self.types()["client"]
        self.assertEqual(row.with_partner, 1)
        self.assertEqual(row.schools_with_visit, 0)
        self.assertEqual(row.partner_slots, 0)

    def test_core_trainings_split_two_staff_and_two_partner(self):
        core = self.school("core", self.cceo)
        for offset in (10, 20, 30):
            self.activity(core, "core_training", owner=self.cceo, on=offset)
        self.activity(
            core,
            "core_training",
            partner=self.partner,
            on=40,
            status="partner_scheduled",
            partner_date_set_by="partner",
        )
        row = self.types()["core"]
        self.assertEqual(row.trainings, 2 + 1)
        self.assertEqual(row.schools_with_training, 1)

    def test_a_cluster_session_trains_only_the_schools_on_its_roster(self):
        named = self.school("client", self.cceo, cluster=self.cluster)
        self.school("client", self.cceo, cluster=self.cluster)
        self.session("cluster_training", [named])
        self.session("cluster_meeting", [named])
        row = self.types()["client"]
        self.assertEqual((row.trainings, row.schools_with_training), (1, 1))
        self.assertEqual((row.clustered, row.in_meeting), (2, 1))

    def reasons(self, school):
        return self.year()[school.id].duplicate_reasons

    def test_one_staff_ssa_support_beside_the_visit_is_not_a_duplicate(self):
        # A Follow up and an SSA Support visit by staff are two kinds of
        # work; a Partner's SSA Support hand-over counts nowhere (owner,
        # 2026-10-03).
        school = self.school("client", self.cceo)
        self.activity(school, "training_follow_up_visit", owner=self.cceo, on=10)
        self.activity(school, "school_visit_ssa_collection", owner=self.cceo, on=20)
        self.handover(
            school,
            self.partner,
            status="pending_scheduling",
            purpose_of_visit="ssa_support",
            expected_activity_type="school_visit_ssa_collection",
        )
        self.assertEqual(self.reasons(school), ())

    def test_the_same_kind_twice_is_a_duplicate(self):
        school = self.school("core_trained", self.cceo)
        self.activity(school, "training_follow_up_visit", owner=self.cceo, on=10)
        self.activity(school, "in_school_training", owner=self.cceo2, on=20)
        self.assertEqual(self.reasons(school), (rules.DUPLICATE_STAFF,))

    def test_staff_and_a_partner_at_one_client_school_is_a_duplicate(self):
        school = self.school("core_graduate", self.cceo)
        self.activity(school, "training_follow_up_visit", owner=self.cceo)
        self.handover(school, self.partner, status="pending_scheduling")
        self.assertEqual(self.reasons(school), (rules.DUPLICATE_BOTH,))
        self.assertEqual([s.id for s in people.duplicates(self.year())], [school.id])

    def test_a_core_school_is_meant_to_have_both(self):
        core = self.school("core", self.cceo)
        self.activity(core, "core_visit", owner=self.cceo)
        self.handover(core, self.partner, status="pending_scheduling")
        self.assertEqual(self.reasons(core), ())


class PeopleFirstPageTest(World):
    """The dashboard's own fold: a row is a person, and it carries their own
    plan beside the schools they hold."""

    def snapshot(self, **filters):
        return svc.snapshot_for(self.cd_user, svc.Filters(fy=FY, **filters))

    def cards(self, snapshot):
        return {card["metric_key"]: card for card in svc.kpis(snapshot)}

    def test_staff_visit_planning_is_plans_over_headcount_targets(self):
        school = self.school("client", self.cceo)
        self.activity(school, "training_follow_up_visit", owner=self.cceo2)
        self.activity(school, "donor_visit", owner=self.cceo2)
        snapshot = self.snapshot()
        card = self.cards(snapshot)["cpo_staff_visit_planning"]
        self.assertEqual(card["part"], "1")
        self.assertEqual(card["whole"], f"{3 * 560 + 2 * 280:,}")
        self.assertEqual(svc.headcount(snapshot), (2, 3))
        # The visit is the planner's; the school is its holder's.
        tree = snapshot.tree
        planner = self.owner_row(tree, self.cceo2).tally
        holder = self.owner_row(tree, self.cceo).tally
        self.assertEqual((planner.p_visits, planner.schools), (1, 0))
        self.assertEqual((holder.p_visits, holder.schools, holder.any_visit), (0, 1, 1))
        self.assertEqual(planner.p_outreach, 1)

    def test_a_leads_row_is_their_own_plan_and_their_cceos(self):
        school = self.school("client", self.cceo)
        other = self.school("client", self.cceo3)
        # The Lead's own SSA Support visit is the Lead's (owner, 2026-10-03);
        # the follow ups are their CCEO's and the other Lead's.
        self.activity(school, "school_visit_ssa_collection", owner=self.pl)
        self.activity(school, "training_follow_up_visit", owner=self.cceo)
        self.activity(other, "training_follow_up_visit", owner=self.cceo3)
        tree = self.snapshot().tree
        lead = self.lead_row(tree, self.pl)
        self.assertEqual(lead.tally.target, 280 + 560 + 560)
        self.assertEqual(lead.tally.p_visits, 2)
        own = self.owner_row(tree, self.pl)
        self.assertEqual(
            (own.kind, own.tally.target, own.tally.p_visits, own.tally.p_outreach),
            ("pl_personal", 280, 1, 0),
        )
        self.assertEqual(self.lead_row(tree, self.pl2).tally.p_visits, 1)
        chart = svc.charts(self.snapshot())[0]
        self.assertEqual(chart["categories"], ["Lead A", "Lead B"])
        series = {s["name"]: s["data"] for s in chart["series"]}
        self.assertEqual(series["Follow up"], [1, 1])
        self.assertEqual(series["SSA Support"], [1, 0])

    def test_a_lead_holding_no_school_still_has_a_row_and_a_target(self):
        tree = self.snapshot().tree
        own = self.owner_row(tree, self.pl2)
        self.assertEqual((own.tally.target, own.tally.schools), (280, 0))
        self.assertEqual(own.tally.shortfall, 280)

    def test_a_lead_using_another_role_keeps_their_team_on_the_page(self):
        self.school("client", self.cceo)
        self.pl_user.roles = [
            EdifyRole.COUNTRY_PROGRAM_LEAD.value,
            EdifyRole.ADMIN.value,
        ]
        self.pl_user.active_role = EdifyRole.ADMIN.value
        self.pl_user.save()
        tree = self.snapshot().tree
        lead = self.lead_row(tree, self.pl)
        self.assertEqual(lead.tally.schools, 1)
        self.assertEqual(lead.tally.target, 280 + 560 + 560)
        self.assertFalse([row for row in tree.leads if row.is_no_lead])

    def test_partner_planning_is_the_partners_dates_over_what_staff_assigned(self):
        waiting = self.school("client", self.cceo)
        booked = self.school("client", self.cceo)
        dated = self.school("client", self.cceo)
        self.handover(
            waiting,
            self.partner,
            status="pending_scheduling",
            assigning_staff_id=self.cceo.id,
        )
        self.activity(
            booked,
            "school_visit",
            partner=self.partner,
            status="partner_scheduled",
            monitored_by_staff_id=self.cceo.id,
            executor_type=ExecutorType.CERTIFIED_PARTNER_AGENCY.value,
            partner_date_set_by="staff",
        )
        snapshot = self.snapshot()
        card = self.cards(snapshot)["cpo_partner_planning"]
        t = snapshot.tree.country
        # Against the Partner's target (owner, 2026-10-03), and nothing until
        # a Partner dates a visit; the work handed over is named beside it.
        self.assertEqual(
            (card["part"], card["whole"]), ("0", f"{t.partner_expected:,}")
        )
        self.assertIn("2 assigned · 2 awaiting the Partner's date", card["extras"])
        # Assigned, never planned: nothing a Partner dated fills a slot yet.
        self.assertEqual((t.partner_assigned, t.partner_scheduled), (2, 0))
        self.assertEqual(t.with_partner, 2)

        self.activity(
            dated,
            "school_visit",
            partner=self.partner2,
            status="partner_scheduled",
            monitored_by_staff_id=self.cceo.id,
            partner_date_set_by="partner",
        )
        svc.snapshot_for(self.cd_user, svc.Filters(fy=FY), refresh=True)
        snapshot = self.snapshot()
        card = self.cards(snapshot)["cpo_partner_planning"]
        self.assertEqual(
            (card["part"], card["whole"]),
            ("1", f"{snapshot.tree.country.partner_expected:,}"),
        )
        self.assertIn("3 assigned · 2 awaiting the Partner's date", card["extras"])
        self.assertEqual(snapshot.tree.country.partner_scheduled, 1)
        rows = {row["name"]: row for row in svc.partner_rows(snapshot, self.cceo.id)}
        self.assertEqual(
            (rows["Partner Alpha"]["assigned"], rows["Partner Alpha"]["planned"]),
            ("2", "0"),
        )
        self.assertEqual(
            (rows["Partner Beta"]["assigned"], rows["Partner Beta"]["planned"]),
            ("1", "1"),
        )

    def test_the_types_table_is_the_cards_split_by_school_type(self):
        core = self.school("core", self.cceo)
        client = self.school("client", self.cceo)
        self.school("core_trained", self.cceo3)
        self.school("core_graduate", self.cceo3)
        self.school("champion", self.cceo3)
        self.activity(core, "core_visit", owner=self.cceo)
        self.activity(client, "training_follow_up_visit", owner=self.cceo)
        self.handover(client, self.partner, status="pending_scheduling")
        snapshot = self.snapshot()
        rows = {row["key"]: row for row in svc.type_rows(snapshot)}
        self.assertEqual(
            [row["key"] for row in svc.type_rows(snapshot) if not row.get("is_total")],
            list(rules.TYPE_ORDER),
        )
        self.assertEqual(
            (
                rows["core"]["visit_slots"],
                rows["core"]["staff"],
                rows["core"]["no_visit"],
            ),
            ("4", "1", "0"),
        )
        self.assertEqual(
            (rows["client"]["any_visit"], rows["client"]["with_partner"]), ("1", "1")
        )
        self.assertEqual(rows["client"]["duplicates"], 1)
        self.assertEqual(rows["core_trained"]["no_visit"], "1")
        self.assertTrue(rows["core_graduate"]["needs_trainings"])
        self.assertFalse(rows["champion"]["needs_visits"])
        self.assertFalse(rows["champion"]["needs_trainings"])
        t = snapshot.tree.country
        self.assertEqual(
            sum(tally.visit_slots for tally in snapshot.tree.by_type.values()),
            t.visit_slots,
        )
        self.assertEqual(t.duplicates, 1)
        self.assertEqual(self.cards(snapshot)["cpo_total_visit_coverage"]["whole"], "7")

    def test_filters_narrow_a_persons_plan_with_the_schools(self):
        east = Region.objects.create(name="Rule East", country="Uganda")
        here = self.school("client", self.cceo)
        there = self.school("core", self.cceo)
        School.objects.filter(pk=there.pk).update(region=east)
        self.activity(here, "training_follow_up_visit", owner=self.cceo)
        self.activity(there, "core_visit", owner=self.cceo, on=20)
        self.activity(there, "core_visit", owner=self.cceo2, on=40)
        self.assertEqual(self.snapshot().tree.country.p_visits, 3)
        self.assertEqual(self.snapshot(region=east.id).tree.country.p_visits, 2)
        self.assertEqual(self.snapshot(school_type="client").tree.country.p_visits, 1)
        self.assertEqual(self.snapshot(cceo=self.cceo2.id).tree.country.p_visits, 1)
        self.assertEqual(
            self.snapshot(program_lead=self.pl2.id).tree.country.p_visits, 0
        )
        full = self.snapshot(planning_status="full").tree.country
        self.assertEqual((full.schools, full.p_visits), (1, 1))
        self.assertEqual(self.snapshot(channel="partner").tree.country.p_visits, 0)

    def test_the_engine_agrees_with_the_school_by_school_read(self):
        """Two readings of the rulebook, written apart, give one answer."""
        core = self.school("core", self.cceo, cluster=self.cluster)
        client = self.school("client", self.cceo)
        trained = self.school("core_trained", self.cceo3)
        graduate = self.school("core_graduate", self.cceo3)
        self.school("champion", self.cceo3)
        for offset in (10, 20, 30):
            self.activity(core, "core_visit", owner=self.cceo, on=offset)
        self.activity(
            core, "core_visit", partner=self.partner, status="partner_scheduled", on=50
        )
        self.activity(core, "core_training", owner=self.cceo, on=60)
        self.activity(
            core,
            "core_training",
            partner=self.partner,
            status="partner_scheduled",
            partner_date_set_by="partner",
            on=70,
        )
        self.activity(client, "training_follow_up_visit", owner=self.cceo)
        self.activity(client, "school_visit_ssa_collection", owner=self.cceo2)
        self.activity(
            trained,
            "in_school_training",
            owner=self.cceo3,
            purpose_type="in_school_training",
        )
        self.handover(trained, self.partner, status="pending_scheduling")
        self.activity(
            graduate,
            "school_visit",
            partner=self.partner2,
            on=None,
            status="assigned_to_partner",
        )
        self.session("cluster_training", [core])
        self.session("cluster_meeting", [core])
        tree = self.snapshot().tree
        year = people.school_year(self.cd_user, FY)
        for row in people.summarise_by_type(year):
            got = tree.by_type.get(row.school_type)
            if got is None:
                self.assertEqual(row.schools, 0)
                continue
            needs = rules.requirement_for(row.school_type)
            with self.subTest(school_type=row.school_type):
                self.assertEqual(
                    (
                        got.schools,
                        got.visit_slots,
                        got.staff,
                        got.partner_scheduled,
                        got.any_visit,
                        got.training_slots,
                        got.training,
                        got.with_partner,
                        got.clustered,
                        got.meeting_covered,
                        got.duplicates,
                    ),
                    (
                        row.schools,
                        row.visit_slots,
                        row.staff_slots,
                        row.partner_slots,
                        row.schools_with_visit if needs.visits else 0,
                        row.training_slots,
                        row.trainings,
                        row.with_partner,
                        row.clustered,
                        row.in_meeting,
                        row.duplicates,
                    ),
                )
        plan = people.people_plan(self.cd_user, FY)
        self.assertEqual(tree.country.p_visits, plan.total("visits_planned"))
        self.assertEqual(tree.country.target, plan.total("target"))
        self.assertEqual(tree.country.pa_work, plan.total("partner_assigned"))
        self.assertEqual(tree.country.pp_work, plan.total("partner_planned"))

    def test_the_page_shows_the_types_and_people_first_columns(self):
        self.school("client", self.cceo)
        client = self.as_user(self.cd_user)
        page = client.get(f"/country-planning-oversight/?fy={FY}").content.decode()
        self.assertIn("Planned and Not Yet Planned by School Type", page)
        self.assertIn("Visits Planned Against Target by Program Lead", page)
        self.assertIn("Core Graduate", page)
        rows = client.get(
            f"/country-planning-oversight/rows?level=lead&key={self.pl.id}&fy={FY}",
            HTTP_HX_REQUEST="true",
        ).content.decode()
        self.assertIn("own plan", rows)
        self.assertIn("/ 560", rows)
