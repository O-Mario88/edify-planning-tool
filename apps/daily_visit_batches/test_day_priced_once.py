"""A day is priced once for all the visits a save adds to it.

Owner, 2026-10-06, on the performance audit's finding F11 ("cost a day once
per save ... it records fewer cost-snapshot versions and audit entries for
the same final figures, so it needs your word"): "work on those".

Two things are held here.

The figures do not move. Each plan below is carried out twice on the same
records, once priced after every school (as it always was, and as
``PRICE_A_DAY_ONCE_PER_SAVE=false`` still does) and once priced when the save
ends, and the whole database is compared between the two: every table of
every app, not a list of the ones somebody thought of. Rows are named by what
they say rather than by the ids each run made up, so "the same" means the
same lines, amounts, periods, advances, weekly and monthly requests, day
pool and transport obligation.

Only the record of the steps nobody saw is shorter, and by exactly those
steps: every snapshot, audit entry and event the new way writes is one the
old way wrote too, and what the old way wrote beyond them is nothing but
superseded snapshots and their "cost calculated" entries.
"""

from __future__ import annotations

import collections
import hashlib
import json
import re
from datetime import date, datetime, timedelta
from unittest import mock

from django.apps import apps as django_apps
from django.db import connection, transaction
from django.test import TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from freezegun import freeze_time

from apps.accounts.models import StaffProfile, StaffSchoolAssignment, User
from apps.activities.models import Activity
from apps.budget.costing_service import active_catalogue
from apps.budget.models import ActivityCostSnapshot, CostSetting
from apps.budget.reference import ensure_active_catalogue
from apps.clusters.models import Cluster
from apps.core.exceptions import BadRequest
from apps.core.rbac import EdifyRole
from apps.geography.models import District, Region, SubCounty
from apps.planning.cluster_bulk_scheduling import bulk_schedule_cluster_visits
from apps.schools.models import School

from .models import DailyVisitBatch
from .services import each_day_priced_once, remove_school
from .tests import PRIMARY_RATES, SECONDARY_RATES

# The week of Monday 3 August 2026; "today" in the fixture is 27 July.
MON, TUE, WED, THU = (date(2026, 8, 3) + timedelta(days=n) for n in range(4))

#: Written by any save about the steps it took: numbered, and fewer of them
#: when a day is priced once.
HISTORY = {"audit_log", "domain_event_log", "activity_cost_snapshot"}
_STEP_NUMBERS = {"sequence", "auditSeq", "is_current", "seq"}
#: A row's own place in a chain, which says where it stands, not what it is.
_PLACE = {"seq", "sequence", "prev_hash", "hash", "supersedes_id", "correlation_id"}


def _plain(value):
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, (dict, list)):
        return json.dumps(value, sort_keys=True, default=str)
    if isinstance(value, (int, float, str, bool, type(None))):
        return value
    return str(value)


#: An id this application makes up for a row: long enough that finding one
#: inside a note or a JSON payload is never a coincidence.
_LONG_ID = re.compile(r"[a-z0-9]{20,}")


def _everything() -> dict[str, tuple[list[str], str | None, dict, list[tuple]]]:
    """Every row of every table, by table, with where its columns point."""
    tables = {}
    with connection.cursor() as cursor:
        for model in django_apps.get_models():
            meta = model._meta
            if meta.proxy or not meta.managed or meta.db_table in tables:
                continue
            columns = [field.column for field in meta.concrete_fields]
            points_at = {
                field.column: field.related_model._meta.db_table
                for field in meta.concrete_fields
                if field.is_relation and field.related_model is not None
            }
            cursor.execute(
                "SELECT %s FROM %s"
                % (
                    ", ".join(connection.ops.quote_name(c) for c in columns),
                    connection.ops.quote_name(meta.db_table),
                )
            )
            tables[meta.db_table] = (
                columns,
                meta.pk.column if meta.pk else None,
                points_at,
                [tuple(_plain(v) for v in row) for row in cursor.fetchall()],
            )
    return tables


class _Compared:
    """Two states of one database, row for row.

    Rows the two share as they stand are set aside. The rest are named by
    their content: an id a run made up is replaced, where a column points at
    its row and wherever it is quoted in a payload, by a name built from what
    the row says. Two runs that wrote the same things under different ids
    then compare equal, and two that did not, do not.
    """

    def __init__(self, first, second, *, started: str):
        self.started = started
        self.tables = {}
        made_up = ({}, {})  # per side: (table, id) -> True
        for table, (columns, key, points_at, rows_a) in first.items():
            rows_b = second[table][3]
            count_a, count_b = collections.Counter(rows_a), collections.Counter(rows_b)
            only = (
                list((count_a - count_b).elements()),
                list((count_b - count_a).elements()),
            )
            if not (only[0] or only[1]):
                continue
            self.tables[table] = (columns, key, points_at, only)
            if key:
                at = columns.index(key)
                for side in (0, 1):
                    theirs = {row[at] for row in only[1 - side]}
                    for row in only[side]:
                        if row[at] not in theirs:
                            made_up[side][(table, row[at])] = True
        self.made_up = made_up
        self.names = (self._names(0), self._names(1))

    def _row(self, side, table, row, names, quoted):
        columns, key, points_at, _only = self.tables[table]
        out = {}
        for column, value in zip(columns, row):
            if column == key and (table, value) in self.made_up[side]:
                continue
            if column in _PLACE:
                continue
            target = points_at.get(column)
            if target and (target, value) in names:
                value = names[(target, value)]
            elif isinstance(value, str):
                # Anything stamped with the moment of the run, and any
                # made-up id quoted in a payload or kept in a plain column.
                value = re.sub(
                    re.escape(self.started) + r"[T ][0-9:.+-]+", "<now>", value
                )
                value = _LONG_ID.sub(
                    lambda found: quoted.get(found.group(0), found.group(0)), value
                )
            out[column] = value
        return out

    def _unnamed(self, side, table, row, names, waiting):
        """Does this row still point at a made-up row that has no name?"""
        columns, _key, points_at, _only = self.tables[table]
        for column, value in zip(columns, row):
            target = points_at.get(column)
            if target and (target, value) in waiting and (target, value) not in names:
                return True
            if isinstance(value, str) and any(
                found in waiting["quoted"] for found in _LONG_ID.findall(value)
            ):
                return True
        return False

    def _names(self, side):
        names, quoted = {}, {}
        waiting = {"quoted": set()}
        for table, (columns, key, _points_at, only) in self.tables.items():
            if not key:
                continue
            at = columns.index(key)
            for row in only[side]:
                if (table, row[at]) in self.made_up[side]:
                    waiting[(table, row[at])] = row
                    if isinstance(row[at], str) and _LONG_ID.fullmatch(row[at]):
                        waiting["quoted"].add(row[at])
        for _ in range(12):
            named = False
            for found, row in list(waiting.items()):
                if found == "quoted":
                    continue
                table, made_up = found
                own = {made_up} if isinstance(made_up, str) else set()
                waiting["quoted"] -= own
                blocked = self._unnamed(side, table, row, names, waiting)
                if blocked:
                    waiting["quoted"] |= own & {
                        key for key in own if _LONG_ID.fullmatch(key)
                    }
                    continue
                text = json.dumps(
                    self._row(side, table, row, names, quoted),
                    sort_keys=True,
                    default=str,
                )
                name = f"<{table}:{hashlib.sha1(text.encode()).hexdigest()[:12]}>"
                names[found] = name
                if isinstance(made_up, str) and _LONG_ID.fullmatch(made_up):
                    quoted[made_up] = name
                del waiting[found]
                named = True
            if not named:
                break
        for found in waiting:
            if found == "quoted":
                continue
            names[found] = f"<{found[0]}>"
            if isinstance(found[1], str) and _LONG_ID.fullmatch(found[1]):
                quoted[found[1]] = names[found]
        self.quoted = getattr(self, "quoted", ()) + (quoted,)
        return names

    def rows(self, table):
        """The differing rows of a table on each side, named."""
        _columns, _key, _points_at, only = self.tables[table]
        return tuple(
            collections.Counter(
                json.dumps(
                    self._row(side, table, row, self.names[side], self.quoted[side]),
                    sort_keys=True,
                    default=str,
                )
                for row in only[side]
            )
            for side in (0, 1)
        )


def _nearest(row_text: str, others) -> str:
    """Where a row with no twin differs from the row most like it."""
    row = json.loads(row_text)
    candidates = [json.loads(text) for text in others]
    if not candidates:
        return "there is no such row at all on the other side"
    nearest = min(
        candidates,
        key=lambda other: sum(1 for key in row if other.get(key) != row.get(key)),
    )
    return "; ".join(
        f"{key}: {str(row.get(key))[:160]!r} against {str(nearest.get(key))[:160]!r}"
        for key in row
        if nearest.get(key) != row.get(key)
    )


def _without_step_numbers(text: str) -> str:
    def clean(value):
        if isinstance(value, dict):
            return {k: clean(v) for k, v in value.items() if k not in _STEP_NUMBERS}
        if isinstance(value, list):
            return [clean(v) for v in value]
        if isinstance(value, str) and value[:1] in "{[":
            try:
                return json.dumps(clean(json.loads(value)), sort_keys=True)
            except ValueError:
                return value
        return value

    return json.dumps(clean(json.loads(text)), sort_keys=True)


# The clock starts on that day and runs. A day's pool is shared out in the
# order its visits were made, which is the order of their ids, and an id
# begins with the millisecond it was made in: on a stopped clock every id of a
# test shares that millisecond, their order is chance, and which school
# carries the first share differs from one run to the next whichever way the
# day is priced.
@freeze_time("2026-07-27", tick=True)
class _ADayOfVisits(TestCase):
    PURPOSE = "ssa_support"

    def setUp(self):
        self.region = Region.objects.create(name="Once Region")
        self.home = District.objects.create(
            name="Once Home District", region=self.region, district_type="primary"
        )
        self.away = District.objects.create(
            name="Once Away District", region=self.region, district_type="secondary"
        )
        self.sub_county = SubCounty.objects.create(name="Once Sub", district=self.home)

        self.catalogue = active_catalogue() or ensure_active_catalogue()
        self.catalogue.is_active = True
        self.catalogue.save(update_fields=["is_active"])
        for key, cost in PRIMARY_RATES + SECONDARY_RATES:
            CostSetting.objects.update_or_create(
                key=key,
                catalogue=self.catalogue,
                defaults={
                    "label": key,
                    "unit_cost": cost,
                    "fy": self.catalogue.fy,
                    "version": 1,
                },
            )

        self.user = User.objects.create_user(
            email="once@test.com",
            name="Once Officer",
            roles=[EdifyRole.CCEO.value],
            active_role=EdifyRole.CCEO.value,
            password="x",
            is_active=True,
        )
        self.staff = StaffProfile.objects.create(
            user=self.user, title="CCEO", country="Uganda"
        )
        self.cluster = Cluster.objects.create(
            name="Once Cluster",
            region=self.region,
            district=self.home,
            sub_county=self.sub_county,
            cluster_type="client",
            status="active",
            responsible_staff_id=self.staff.id,
        )
        self.near = [self._school(f"ONCE-H-{n}", self.home) for n in range(1, 11)]
        self.far = [self._school(f"ONCE-A-{n}", self.away) for n in range(1, 8)]

    def _school(self, code, district):
        school = School.objects.create(
            school_id=code,
            name=f"School {code}",
            region=self.region,
            district=district,
            sub_county=self.sub_county,
            school_type="client",
            account_owner_id=self.staff.id,
            cluster_id=self.cluster.id,
            cluster_status="clustered",
            current_fy_ssa_status="done",
            planning_readiness="ready",
        )
        StaffSchoolAssignment.objects.create(staff=self.staff, school_id=school.id)
        return school

    def plan(self, day, schools, **overrides):
        return bulk_schedule_cluster_visits(
            self.cluster.id,
            {
                "purposeOfVisit": self.PURPOSE,
                "scheduledDate": day.isoformat(),
                "schoolIds": [school.id for school in schools],
                **overrides,
            },
            self.user,
        )

    def both_ways(self, steps):
        """Carry `steps` out priced after each school, undo them, carry them
        out priced once, and return (comparison, statements each way)."""
        states, statements = [], []
        for once in (False, True):
            with transaction.atomic():
                with override_settings(PRICE_A_DAY_ONCE_PER_SAVE=once):
                    with CaptureQueriesContext(connection) as queries:
                        steps()
                statements.append(len(queries))
                states.append(_everything())
                transaction.set_rollback(True)
        return _Compared(*states, started="2026-07-27"), statements

    def assertSameFigures(self, compared):
        """Every table but the history is the same; the history of the new
        way is part of the history of the old."""
        surplus = {}
        for table in sorted(compared.tables):
            each, once = compared.rows(table)
            if table not in HISTORY:
                for text in (once - each) or (each - once):
                    self.fail(
                        f"{table} ends differently when a day is priced once: "
                        + _nearest(text, each if text in once else once)
                    )
                continue
            each = collections.Counter(
                _without_step_numbers(text) for text in each.elements()
            )
            once = collections.Counter(
                _without_step_numbers(text) for text in once.elements()
            )
            for text in once - each:
                self.fail(
                    f"{table}: pricing once recorded something pricing after "
                    "each school did not: " + _nearest(text, each)
                )
            kinds = collections.Counter()
            for text, count in (each - once).items():
                row = json.loads(text)
                kinds[
                    row.get("action")
                    or row.get("event_type")
                    or ("snapshot" if "operational_breakdown" in row else "?")
                ] += count
            surplus[table] = dict(kinds)
        return surplus


class TheFiguresAreTheSameTest(_ADayOfVisits):
    def test_five_schools_on_an_empty_day(self):
        compared, (each, once) = self.both_ways(lambda: self.plan(MON, self.near[:5]))
        surplus = self.assertSameFigures(compared)
        # 1+2+3+4+5 pricings became 5: ten snapshots fewer, and ten "cost
        # calculated" audit entries (and the event each one publishes, where
        # events are being published).
        self.assertEqual(surplus.pop("activity_cost_snapshot"), {"snapshot": 10})
        self.assertEqual(surplus.pop("audit_log"), {"activity.cost.calculated": 10})
        self.assertIn(
            surplus, ({}, {"domain_event_log": {"activity.cost.calculated": 10}})
        )
        self.assertLess(once, each)
        # The tables that carry the money were written, and compared.
        for table in (
            "activity",
            "activity_schedule_cost_line",
            "advance_request",
            "daily_visit_batch",
            "weekly_fund_request",
            "weekly_fund_request_line",
        ):
            self.assertIn(table, compared.tables)

    def test_five_more_join_a_day_that_holds_five(self):
        def steps():
            self.plan(MON, self.near[:5])
            self.plan(MON, self.near[5:10])

        compared, (each, once) = self.both_ways(steps)
        surplus = self.assertSameFigures(compared)
        # 15 + 40 pricings became 5 + 10.
        self.assertEqual(surplus["activity_cost_snapshot"], {"snapshot": 40})
        self.assertLess(once, each * 0.6)

    def test_a_day_away_among_schools_at_home(self):
        """One school in a secondary district makes the whole day a day away:
        every school on it shares transport, meals and the night."""
        compared, _ = self.both_ways(
            lambda: self.plan(MON, self.near[:2] + self.far[:2] + self.near[2:3])
        )
        self.assertSameFigures(compared)
        self.assertIn("activity_schedule_cost_line", compared.tables)

    def test_a_third_day_away_gives_the_second_its_night_back(self):
        """Tuesday is the day home of a Monday-to-Tuesday trip until Wednesday
        is planned; then Tuesday has a night and a dinner again, and is
        re-priced with Wednesday's save (apps.daily_visit_batches.return_day)."""

        def steps():
            self.plan(MON, self.far[:1])
            self.plan(TUE, self.far[1:2])
            self.plan(WED, self.far[2:5])

        compared, _ = self.both_ways(steps)
        self.assertSameFigures(compared)

    def test_days_of_one_two_three_and_four(self):
        def steps():
            self.plan(MON, self.near[:1])
            self.plan(TUE, self.near[1:3])
            self.plan(WED, self.near[3:6])
            self.plan(THU, self.near[6:10])

        compared, _ = self.both_ways(steps)
        self.assertSameFigures(compared)


class WhatIsRefusedIsStillRefusedTest(_ADayOfVisits):
    def test_a_member_whose_advance_is_confirmed_stops_the_whole_day(self):
        """Adding to a day re-prices who is on it, and a member whose money
        is already with the accountant may not be re-priced. That refusal
        used to come with the first school added; it comes when the day is
        priced now, and still leaves nothing written."""
        from apps.fund_requests.models import AdvanceRequest, AdvanceRequestStatus

        self.plan(MON, self.near[:2])
        AdvanceRequest.objects.filter(
            budget_line__activity__school=self.near[0]
        ).update(status=AdvanceRequestStatus.CONFIRMED_FOR_ADVANCE)
        messages = []
        for once in (False, True):
            before = Activity.objects.count()
            with override_settings(PRICE_A_DAY_ONCE_PER_SAVE=once):
                with self.assertRaises(BadRequest) as refused:
                    self.plan(MON, self.near[2:5])
            messages.append(str(refused.exception.detail))
            self.assertEqual(Activity.objects.count(), before)
        self.assertEqual(messages[0], messages[1])
        self.assertIn("accountant", messages[0])


class TheBlockTest(_ADayOfVisits):
    def test_each_visit_has_one_snapshot_not_one_per_school_added(self):
        created = self.plan(MON, self.near[:5])["created"]
        self.assertEqual(
            sorted(
                ActivityCostSnapshot.objects.filter(activity_id__in=created)
                .values_list("activity_id", "sequence")
                .order_by("activity_id")
            ),
            sorted((activity_id, 1) for activity_id in created),
        )
        batch = DailyVisitBatch.objects.get(
            responsible_user=self.user.id, visit_date=MON
        )
        self.assertEqual(batch.school_count, 5)
        for activity in Activity.objects.filter(id__in=created):
            self.assertGreater(activity.est_cost_cents, 0)
            self.assertFalse(activity.cost_missing)

    def test_the_switch_prices_after_every_school_again(self):
        with override_settings(PRICE_A_DAY_ONCE_PER_SAVE=False):
            created = self.plan(MON, self.near[:3])["created"]
        self.assertEqual(
            sorted(
                ActivityCostSnapshot.objects.filter(
                    activity_id__in=created, is_current=True
                ).values_list("sequence", flat=True)
            ),
            [1, 2, 3],
        )

    def test_a_block_inside_a_block_leaves_the_pricing_to_the_outer_one(self):
        with each_day_priced_once():
            with each_day_priced_once():
                self.plan(MON, self.near[:2])
            # The inner block has ended and nothing is priced yet.
            self.assertFalse(ActivityCostSnapshot.objects.exists())
            self.plan(MON, self.near[2:4])
        self.assertEqual(ActivityCostSnapshot.objects.count(), 4)

    def test_a_visit_leaving_a_day_is_priced_at_once(self):
        """Only joining waits. What follows a visit leaving its day reads the
        price of the day it left."""
        first, second = self.plan(MON, self.near[:2])["created"]
        with each_day_priced_once():
            remove_school(activity_id=first)
            self.assertEqual(
                ActivityCostSnapshot.objects.filter(activity_id=second, is_current=True)
                .get()
                .sequence,
                2,
            )

    def test_it_refuses_to_run_outside_a_transaction(self):
        with mock.patch.object(connection, "in_atomic_block", False):
            with self.assertRaises(RuntimeError):
                with each_day_priced_once():
                    pass  # pragma: no cover

    def test_a_failure_inside_the_block_prices_nothing(self):
        with self.assertRaises(ZeroDivisionError):
            with each_day_priced_once():
                self.plan(MON, self.near[:2])
                1 / 0
        self.assertFalse(ActivityCostSnapshot.objects.exists())
        # And the next save is not left waiting behind it.
        self.plan(TUE, self.near[2:3])
        self.assertEqual(ActivityCostSnapshot.objects.count(), 1)


class TheSaveStaysShortTest(_ADayOfVisits):
    """Counted, so it reads the same on a loaded runner. On the copy grown to
    production's size the same two saves went from 1,053 statements to 578 and
    from 2,007 to 792 (2026-10-06)."""

    #: Statements for five schools on an empty day, and for five more on it:
    #: 590 and 817 on these records, with a little room. Priced after every
    #: school they are 1,109 and 2,156.
    EMPTY_DAY = 620
    DAY_OF_FIVE = 860

    def test_five_schools_on_an_empty_day_and_five_more(self):
        # The first save of a process reads what later ones find held.
        self.plan(THU, self.far[:1])
        with CaptureQueriesContext(connection) as first:
            self.plan(MON, self.near[:5])
        with CaptureQueriesContext(connection) as second:
            self.plan(MON, self.near[5:10])
        self.assertLessEqual(len(first), self.EMPTY_DAY, len(first))
        self.assertLessEqual(len(second), self.DAY_OF_FIVE, len(second))
