"""The consolidated tables behind the Country Director's cards (owner,
2026-10-01): each card links to the table of what it counts, grouped by
Programme Lead, and a table that lists schools carries the School ID."""

from __future__ import annotations

import io
import re

from apps.core.enums import ExecutorType
from apps.geography.models import SubRegion
from apps.planning.country_oversight import service as svc
from apps.planning.country_oversight import tables
from apps.planning.test_country_planning_oversight import FY, World


class TableWorld(World):
    def table(self, key, **filters):
        return tables.build(self.cd_user, svc.Filters(fy=FY, **filters), key)

    def page(self, key, user=None, query=""):
        return self.as_user(user or self.cd_user).get(
            f"/country-planning-oversight/table/{key}?fy={FY}{query}"
        )

    def country(self, **filters):
        return svc.snapshot_for(
            self.cd_user, svc.Filters(fy=FY, **filters)
        ).tree.country


class TableRulesTest(TableWorld):
    def test_every_card_opens_a_table(self):
        self.assertEqual(tables.METRIC_TABLES, svc.KPI_TABLES)
        self.assertEqual(set(svc.KPI_TABLES), set(svc.KPI_KEYS))
        self.assertEqual(set(tables.TAB_ORDER), set(tables.SPECS))

    def test_a_table_that_lists_schools_carries_the_school_id(self):
        """Owner, 2026-10-01: "every consolidated table with list of school
        should have school ID" — beside the school, on the page and in the
        workbook."""
        for spec in tables.SPECS.values():
            keys = [column.key for column in spec.columns]
            with self.subTest(table=spec.key):
                if "school" in keys:
                    self.assertIn("school_id", keys)
                    self.assertEqual(keys.index("school_id") + 1, keys.index("school"))
                    self.assertNotIn("school_id", spec.groups)

    def test_every_table_is_grouped_by_programme_lead_first(self):
        for spec in tables.SPECS.values():
            with self.subTest(table=spec.key):
                self.assertEqual(spec.groups[0], "lead")
                self.assertEqual(spec.columns[0].label, "Programme Lead")


class PeopleTablesTest(TableWorld):
    def test_the_visit_table_lists_exactly_what_the_card_counts(self):
        here = self.school("client", self.cceo)
        there = self.school("core", self.cceo3)
        self.activity(here, "training_follow_up_visit", owner=self.cceo2, on=30)
        self.activity(here, "school_visit_ssa_collection", owner=self.pl, on=20)
        self.activity(there, "core_visit", owner=self.cceo3, on=10)
        self.activity(here, "donor_visit", owner=self.cceo)
        table = self.table("visits")
        self.assertEqual(len(table.rows), self.country().p_visits)
        self.assertEqual(
            [(row["lead"], row["staff"], row["activity"]) for row in table.rows],
            [
                ("Lead A", "Lead A", "SSA Support"),
                ("Lead A", "Officer Two", "Follow up"),
                ("Lead B", "Officer Three", "Follow up"),
            ],
        )
        self.assertEqual(table.rows[0]["school_id"], here.school_id)
        self.assertEqual(table.summary, "3 visits planned")
        # The page's Programme Lead choice keeps that Lead's team.
        self.assertEqual(len(self.table("visits", program_lead=self.pl2.id).rows), 1)
        self.assertEqual(len(self.table("visits", school_type="core").rows), 1)

    def test_the_partner_table_shows_assigned_and_what_the_partner_dated(self):
        waiting = self.school("client", self.cceo)
        booked = self.school("client", self.cceo)
        dated = self.school("core_trained", self.cceo3)
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
        self.activity(
            dated,
            "school_visit_ssa_collection",
            partner=self.partner2,
            status="partner_scheduled",
            monitored_by_staff_id=self.cceo3.id,
            partner_date_set_by="partner",
        )
        table = self.table("partners")
        country = self.country()
        self.assertEqual(len(table.rows), country.pa_work)
        states = {row["school_id"]: row["state"] for row in table.rows}
        self.assertEqual(states[waiting.school_id], "Awaiting the Partner's date")
        self.assertEqual(states[booked.school_id], "Dated by staff, not by the Partner")
        self.assertEqual(states[dated.school_id], "Planned by the Partner")
        self.assertEqual(
            sum(1 for state in states.values() if state == "Planned by the Partner"),
            country.pp_work,
        )
        by_school = {row["school_id"]: row for row in table.rows}
        self.assertIsNone(by_school[waiting.school_id]["date"])
        self.assertEqual(by_school[waiting.school_id]["staff"], "Officer One")
        self.assertEqual(by_school[dated.school_id]["partner"], "Partner Beta")
        self.assertEqual(by_school[dated.school_id]["activity"], "SSA Support")
        self.assertIn("1 planned by the Partner", table.summary)

    def test_all_plans_lists_each_activity_once(self):
        school = self.school("client", self.cceo, cluster=self.cluster)
        self.activity(
            school,
            "in_school_training",
            owner=self.cceo,
            purpose_type="in_school_training",
        )
        self.activity(school, "donor_visit", owner=self.cceo)
        self.session("cluster_meeting", [school])
        self.session("cluster_training", [school])
        self.handover(school, self.partner, status="pending_scheduling")
        table = self.table("plans")
        self.assertEqual(len(table.rows), 5)
        counted = {row["activity"]: row["counted"] for row in table.rows}
        self.assertEqual(counted["In-school Training"], "Yes")
        self.assertEqual(counted["Donor Visit"], "No")
        trainings = self.table("trainings")
        # The in-school training is a training too; the cluster training
        # reaches the school on its roster.
        self.assertEqual(len(trainings.rows), 2)
        self.assertEqual(
            sorted(row["invited"] for row in trainings.rows if "invited" in row), [1]
        )

    def test_cluster_tables_group_by_lead_sub_region_district_and_cluster(self):
        sub_region = SubRegion.objects.create(name="Rule Buganda", region=self.region)
        self.district.sub_region = sub_region
        self.district.save()
        self.cluster.responsible_staff_id = self.cceo2.id
        self.cluster.save()
        member = self.school("client", self.cceo, cluster=self.cluster)
        self.school("client", self.cceo)
        self.session("cluster_meeting", [member])
        clusters = self.table("clusters")
        self.assertEqual(len(clusters.rows), self.country().clustered)
        row = clusters.rows[0]
        self.assertEqual(
            clusters.group_of(row),
            ("Lead A", "Rule Buganda", "CPO Kampala", "CPO Cluster"),
        )
        # The CCEO responsible for the cluster, not whoever holds the school.
        self.assertEqual(row["staff"], "Officer Two")
        self.assertEqual(row["school_id"], member.school_id)
        meetings = self.table("meetings")
        self.assertEqual(len(meetings.rows), self.country().p_meetings)
        meeting = meetings.rows[0]
        self.assertEqual(
            meetings.group_of(meeting),
            ("Lead A", "Rule Buganda", "CPO Kampala", "CPO Cluster"),
        )
        self.assertEqual((meeting["staff"], meeting["invited"]), ("Officer One", 1))


class SchoolTablesTest(TableWorld):
    def test_planned_twice_lists_every_plan_under_its_school(self):
        """One unique school, however many plans: the duplicate is shown with
        each plan that makes it, never removed."""
        twice = self.school("client", self.cceo)
        self.activity(twice, "training_follow_up_visit", owner=self.cceo2, on=10)
        self.handover(
            twice,
            self.partner,
            status="pending_scheduling",
            assigning_staff_id=self.cceo.id,
        )
        self.activity(
            twice,
            "school_visit_ssa_collection",
            partner=self.partner2,
            status="partner_scheduled",
            partner_date_set_by="partner",
            on=40,
        )
        self.school("client", self.cceo3)
        country = self.country()
        self.assertEqual(country.duplicates, 1)
        # Coverage counts the school once.
        self.assertEqual((country.any_visit, country.planned), (1, 1))
        table = self.table("duplicates")
        self.assertEqual(len(table.rows), 3)
        self.assertEqual({row["school_id"] for row in table.rows}, {twice.school_id})
        self.assertEqual(
            sorted((row["channel"], row["staff"]) for row in table.rows),
            [
                ("Partner", "Partner Alpha (assigned by Officer One)"),
                ("Partner", "Partner Beta (assigned by Officer One)"),
                ("Staff", "Officer Two"),
            ],
        )
        row = table.rows[0]
        # Under whoever HOLDS the school, whoever planned there.
        self.assertEqual((row["lead"], row["holder"]), ("Lead A", "Officer One"))
        self.assertEqual(row["why"], "Planned by staff and held by a Partner")
        self.assertEqual(table.summary, "1 school planned twice · 3 plans between them")

    def test_a_plan_at_a_school_planned_twice_is_flagged_where_it_is_listed(self):
        twice = self.school("client", self.cceo)
        once = self.school("client", self.cceo)
        self.activity(twice, "training_follow_up_visit", owner=self.cceo, on=10)
        self.activity(twice, "training_follow_up_visit", owner=self.cceo, on=20)
        self.activity(once, "training_follow_up_visit", owner=self.cceo, on=30)
        flags = {(row["school_id"], row["flag"]) for row in self.table("visits").rows}
        self.assertEqual(
            flags, {(twice.school_id, "Planned twice"), (once.school_id, "")}
        )
        # Both instances are listed: the count of plans is not reduced.
        self.assertEqual(len(self.table("visits").rows), 3)
        self.assertEqual(self.country().p_visits, 3)
        self.assertEqual(self.country().any_visit, 2)

    def test_a_core_school_with_more_visits_than_it_takes_is_captured(self):
        core = self.school("core", self.cceo)
        for offset in (10, 20, 30):
            self.activity(core, "core_visit", owner=self.cceo, on=offset)
        country = self.country()
        self.assertEqual((country.duplicates, country.staff), (1, 2))
        table = self.table("duplicates")
        self.assertEqual(len(table.rows), 3)
        self.assertEqual(
            table.rows[0]["why"], "More staff visits than a Core school takes"
        )

    def test_not_yet_planned_no_training_and_unclustered_match_the_page(self):
        open_core = self.school("core", self.cceo3)
        self.school("champion", self.cceo3)
        clustered = self.school("client", self.cceo, cluster=self.cluster)
        self.activity(clustered, "training_follow_up_visit", owner=self.cceo)
        country = self.country()
        not_planned = self.table("not-planned")
        self.assertEqual(len(not_planned.rows), country.no_visit)
        # A Champion school needs no visit: it is not "not yet planned".
        self.assertEqual(
            [row["school_id"] for row in not_planned.rows], [open_core.school_id]
        )
        self.assertEqual(len(self.table("no-training").rows), country.no_training)
        self.assertEqual(len(self.table("unclustered").rows), country.unclustered)
        self.assertEqual(len(self.table("not-planned", school_type="client").rows), 0)


class BalancesTest(TableWorld):
    """Planned AND remaining, at each level (owner, 2026-10-01)."""

    def headings(self, key, **filters):
        table = self.table(key, **filters)
        page = tables.page_of(table, 1)
        return [line for line in page["lines"] if line.get("heading")]

    def test_the_visit_table_states_each_leads_and_each_persons_balance(self):
        school = self.school("client", self.cceo)
        self.activity(school, "training_follow_up_visit", owner=self.cceo)
        self.activity(school, "school_visit_ssa_collection", owner=self.pl, on=40)
        headings = self.headings("visits")
        self.assertEqual(
            [(h["depth"], h["heading"], h["count"]) for h in headings],
            [
                (0, "Lead A", "2 visits"),
                (1, "Lead A", "1 visit"),
                (1, "Officer One", "1 visit"),
            ],
        )
        self.assertEqual(headings[0]["note"], "2 of 1,400 planned · 1,398 to plan")
        self.assertEqual(headings[1]["note"], "1 of 280 planned · 279 to plan")
        self.assertEqual(headings[2]["note"], "1 of 560 planned · 559 to plan")

    def test_the_partner_table_states_what_the_partner_has_dated(self):
        school = self.school("client", self.cceo)
        self.handover(
            school,
            self.partner,
            status="pending_scheduling",
            assigning_staff_id=self.cceo.id,
        )
        headings = self.headings("partners")
        self.assertEqual([h["heading"] for h in headings], ["Lead A", "Officer One"])
        self.assertEqual(
            headings[1]["note"],
            "0 of 1 planned by the Partner · 1 awaiting the Partner's date",
        )


class CardsAreTheirTablesTest(TableWorld):
    """KPI → table → records: the number on a card is the number of records
    its table lists, and the levels add up."""

    def setUp(self):
        core = self.school("core", self.cceo, cluster=self.cluster)
        client = self.school("client", self.cceo, cluster=self.cluster)
        other = self.school("core_trained", self.cceo3)
        self.school("core_graduate", self.cceo3)
        self.school("champion", self.cceo2)
        self.activity(core, "core_visit", owner=self.cceo, on=10)
        self.activity(client, "training_follow_up_visit", owner=self.cceo2, on=20)
        self.activity(other, "school_visit_ssa_collection", owner=self.pl2, on=30)
        self.activity(other, "donor_visit", owner=self.cceo3, on=35)
        self.handover(
            client,
            self.partner,
            status="pending_scheduling",
            assigning_staff_id=self.cceo.id,
        )
        self.activity(
            core,
            "core_visit",
            partner=self.partner2,
            status="partner_scheduled",
            partner_date_set_by="partner",
            monitored_by_staff_id=self.cceo.id,
            on=50,
        )
        self.session("cluster_meeting", [core])
        self.session("cluster_training", [client])

    def cards(self, **filters):
        snapshot = svc.snapshot_for(self.cd_user, svc.Filters(fy=FY, **filters))
        return {
            card["metric_key"]: (
                int(card["part"].replace(",", "")),
                int(card["whole"].replace(",", "")),
            )
            for card in svc.kpis(snapshot)
        }, snapshot

    def test_each_card_is_the_count_of_its_tables_records(self):
        for filters in ({}, {"program_lead": self.pl.id}, {"school_type": "core"}):
            with self.subTest(filters=filters):
                cards, snapshot = self.cards(**filters)
                country = snapshot.tree.country
                visits = self.table("visits", **filters)
                self.assertEqual(len(visits.rows), cards["cpo_staff_visit_planning"][0])
                partners = self.table("partners", **filters)
                self.assertEqual(len(partners.rows), cards["cpo_partner_planning"][1])
                self.assertEqual(
                    sum(
                        1 for r in partners.rows if r["state"] == tables.PARTNER_PLANNED
                    ),
                    cards["cpo_partner_planning"][0],
                )
                self.assertEqual(
                    len(self.table("clusters", **filters).rows),
                    cards["cpo_cluster_membership"][0]
                    if not filters.get("program_lead")
                    else len(self.table("clusters", **filters).rows),
                )
                self.assertEqual(
                    len(self.table("meetings", **filters).rows), country.p_meetings
                )
                self.assertEqual(
                    len(self.table("not-planned", **filters).rows), country.no_visit
                )
                self.assertEqual(
                    len(self.table("no-training", **filters).rows), country.no_training
                )
                plans = self.table("plans", **filters)
                self.assertEqual(
                    sum(1 for r in plans.rows if r["counted"] == "Yes"),
                    country.p_visits,
                )
                self.assertEqual(
                    sum(1 for r in plans.rows if r["counted"] == "No"),
                    country.p_outreach,
                )

    def test_country_is_its_leads_and_each_lead_its_people(self):
        _cards, snapshot = self.cards()
        tree = snapshot.tree
        for field in (
            "target",
            "p_visits",
            "pa_work",
            "pp_work",
            "p_meetings",
            "visit_slots",
            "staff",
            "partner_scheduled",
            "any_visit",
            "no_visit",
            "training",
            "duplicates",
        ):
            with self.subTest(field=field):
                self.assertEqual(
                    getattr(tree.country, field),
                    sum(getattr(lead.tally, field) for lead in tree.leads),
                )
                for lead in tree.leads:
                    self.assertEqual(
                        getattr(lead.tally, field),
                        sum(getattr(owner.tally, field) for owner in lead.owners),
                    )

    def test_the_type_rows_add_up_to_the_cards(self):
        cards, snapshot = self.cards()
        rows = svc.type_rows(snapshot)
        total = rows[-1]
        self.assertTrue(total["is_total"])
        number = lambda text: int(text.replace(",", ""))  # noqa: E731
        types = rows[:-1]
        for key in ("schools", "visit_slots", "staff", "partner_scheduled", "training"):
            with self.subTest(column=key):
                self.assertEqual(
                    sum(number(row[key]) for row in types), number(total[key])
                )
        self.assertEqual(
            (
                number(total["staff"]) + number(total["partner_scheduled"]),
                number(total["visit_slots"]),
            ),
            cards["cpo_total_visit_coverage"],
        )
        self.assertEqual(
            (number(total["training"]), number(total["training_slots"])),
            cards["cpo_training_planning"],
        )
        core = next(row for row in types if row["key"] == "core")
        self.assertEqual(
            (core["visit_slots"], core["staff"], core["partner_scheduled"]),
            ("4", "1", "1"),
        )
        self.assertEqual(core["visit_remaining"], "2")


class TablePageTest(TableWorld):
    def test_the_cards_are_links_to_their_tables(self):
        self.school("client", self.cceo)
        body = (
            self.as_user(self.cd_user)
            .get(f"/country-planning-oversight/?fy={FY}")
            .content.decode()
        )
        for key in svc.KPI_TABLES.values():
            with self.subTest(table=key):
                self.assertRegex(
                    body,
                    rf'<a class="cpo-metric"[^>]*href="/country-planning-oversight/table/{key}\?',
                )
        self.assertIn(
            "/country-planning-oversight/table/not-planned?school_type=client", body
        )

    def test_a_table_page_shows_groups_school_ids_and_one_export(self):
        school = self.school("client", self.cceo)
        self.activity(school, "training_follow_up_visit", owner=self.cceo)
        response = self.page("visits")
        self.assertEqual(response.status_code, 200)
        body = response.content.decode()
        self.assertIn("Staff Visit Plans", body)
        self.assertIn('<span class="edify-group-head__label">Lead A</span>', body)
        self.assertIn(">School ID</th>", body)
        self.assertIn(f">{school.school_id}</td>", body)
        self.assertIn(f'href="/schools/{school.school_id}"', body)
        self.assertEqual(
            body.count("/country-planning-oversight/table-export/visits"), 1
        )
        # Every table is a tab away.
        for key in tables.TAB_ORDER:
            self.assertIn(f"/country-planning-oversight/table/{key}?", body)

    def test_every_table_opens_and_exports(self):
        import openpyxl

        school = self.school("client", self.cceo, cluster=self.cluster)
        self.activity(school, "training_follow_up_visit", owner=self.cceo)
        client = self.as_user(self.cd_user)
        for key, spec in tables.SPECS.items():
            with self.subTest(table=key):
                self.assertEqual(self.page(key).status_code, 200)
                export = client.get(
                    f"/country-planning-oversight/table-export/{key}?fy={FY}"
                )
                self.assertEqual(export.status_code, 200)
                sheet = openpyxl.load_workbook(io.BytesIO(export.content)).active
                headers = [cell.value for cell in sheet[1]]
                # The workbook carries the groups as columns.
                self.assertEqual(headers, [column.label for column in spec.columns])
                self.assertEqual(headers[0], "Programme Lead")

    def test_a_long_table_is_paged_and_keeps_its_filters(self):
        school = self.school("client", self.cceo)
        for offset in range(tables.ROWS_PER_PAGE + 5):
            self.activity(
                school, "training_follow_up_visit", owner=self.cceo, on=offset
            )
        body = self.page("visits", query=f"&program_lead={self.pl.id}").content.decode()
        self.assertEqual(
            len(re.findall(r">Follow up</td>", body)), tables.ROWS_PER_PAGE
        )
        self.assertIn("page=2", body)
        self.assertIn(f"program_lead={self.pl.id}", body)
        second = self.page("visits", query="&page=2").content.decode()
        self.assertEqual(len(re.findall(r">Follow up</td>", second)), 5)
        # The heading says how many the whole group holds, on every page.
        self.assertIn(f"{tables.ROWS_PER_PAGE + 5} visits", second)

    def test_who_may_open_a_table(self):
        self.school("client", self.cceo)
        for user, allowed in (
            (self.cd_user, True),
            (self.ia_user, True),
            (self.pl_user, False),
            (self.cceo_user, False),
        ):
            with self.subTest(role=user.active_role):
                status = self.page("visits", user).status_code
                self.assertEqual(status == 200, allowed)
        # The RVP reads the country's figures, never its school rows.
        body = self.page("visits", self.rvp_user).content.decode()
        self.assertIn("School-level rows are not part of this role", body)
        self.assertNotIn("edify-group-head__label", body)
        self.assertEqual(self.page("nonsense").status_code, 404)
