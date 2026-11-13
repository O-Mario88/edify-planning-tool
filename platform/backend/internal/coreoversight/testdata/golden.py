"""Write golden.json.gz: Core School Oversight as the existing application
answers it for records the development seed does not hold.

    python manage.py shell < platform/backend/internal/coreoversight/testdata/golden.py

Each case is a set of records as the page's statements would return them
(made here from a seeded random source, so every rule the page applies is
reached: SSA records with and without an average of their own, pairs judged
by published rules and by the fallback, readings too close to compare,
plans filed under a school's id and under its School ID, plans with no
target and plans over-delivered, partner hand-overs, registers and the
schools' own trainings, enrolment from nothing, weighted class results,
stored and judged Champions, live plans of the running year and of others,
recommendations in every state, schools sharing a name, and tables of more
than one page), the reader, the query, and the page the existing
application's own code makes of them: apps.core_schools.intelligence and
champion_services, apps.ssa.change_rules and year_comparison,
apps.analytics.impact_engine.improvement_rows, apps.clusters.outcomes, the
page's view and template, and the app's feed reader, all unmodified. Only
the statements themselves are stood in for (and package_splits, whose
figures the page does not show), so nothing is read from or written to the
database beyond the reader's own account. page_golden_test.go gives the same
records to Go and expects the same page.
"""

import gzip
import json
import random
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace as NS
from unittest import mock

from django.contrib.auth import get_user_model

from apps.activities.models import Activity, ClusterActivityAttendance
from apps.analytics import impact_engine
from apps.clusters import oversight_service
from apps.clusters.models import Cluster
from apps.core.enums import SchoolType, SsaIntervention
from apps.core.fy import fy_options
from apps.core_schools import champion_services, intelligence, package_split
from apps.core_schools.models import CorePlan, CoreSchoolProfile
from apps.frontend.views import core_oversight_views
from apps.geography.models import SubRegion
from apps.impact.models import LearningAssessmentResult
from apps.mobile_feed.views import read_page
from apps.partners.models import PartnerAssignment
from apps.schools.models import School, SchoolEnrollmentHistory
from apps.ssa import change_rules
from apps.ssa.models import SsaRecord, SsaScore
from apps.ssa.recommendation_models import SsaRecommendation

OUT = Path("platform/backend/internal/coreoversight/testdata/golden.json.gz")
AREAS = [i.value for i in SsaIntervention]
TYPES = dict(SchoolType.choices)
STATES = ["generated", "accepted", "deferred", "planned", "rejected", "delivered"]
STATE_LABELS = {
    "generated": "Generated",
    "accepted": "Accepted for planning",
    "deferred": "Deferred",
    "planned": "Planned",
    "rejected": "Rejected",
    "delivered": "Delivered and verified",
}


class Fake:
    """A manager whose chain of calls is answered by ``answer(calls)``: each
    filter / values / order_by … is recorded, and iterating asks."""

    def __init__(self, answer, calls=()):
        self._answer, self._calls = answer, list(calls)

    def __getattr__(self, name):
        if name.startswith("__") or name == "keys":
            raise AttributeError(name)

        def step(*args, **kwargs):
            return Fake(self._answer, [*self._calls, (name, args, kwargs)])

        return step

    def __iter__(self):
        return iter(self._answer(self._calls))

    def first(self):
        rows = list(self)
        return rows[0] if rows else None


def called(calls, name):
    return [c for c in calls if c[0] == name]


def kw(calls, key):
    for _name, _args, kwargs in calls:
        if key in kwargs:
            return kwargs[key]
    return None


def make(seed, *, schools, fy="2027", operational="2027", rules=True):
    # Made-up records for a test, repeatable from the seed: not a secret.
    rnd = random.Random(seed)  # nosec B311
    previous = str(int(fy) - 1)
    world = {"schools": [], "ssa": [], "recs": []}
    rec = {
        "schools": [], "owners": {"own-1": "Grace A.", "u-own-1": "Grace A.", "own-2": "paul@example.org", "own-3": "Unnamed"},
        "clusters": {"cl1": "Cluster One", "cl2": "  Cluster   Two ", "cl3": "Kasawo"},
        "sub_regions": {"sr1": "Central", "sr2": "Busoga"},
        "year_records": [], "year_carried": [], "current_records": [], "current_scores": [],
        "countries": {}, "change_rules": [], "latest_now": [], "latest_before": [], "pair_scores": [],
        "plans": [], "handovers": [], "register": [], "trainings": [], "enrolment": [], "learning": [],
        "stored": [], "scan_profiles": [], "scan_plans": [], "scan_ssas": [], "scan_scores": [],
        "scan_schools": [], "recommendations": [],
    }  # fmt: skip
    names = [
        "Kimenyedde Primary",
        "kimenyedde primary",
        "Goma  Hill",
        "Ntenjeru C/U",
        "Bright & Co Academy",
        "Zeta",
    ]
    created = datetime(2026, 1, 1, tzinfo=timezone.utc)
    record_no = 0
    for n in range(schools):
        sid = f"s{n:03d}"
        code = "" if n == 3 else str(1000 + n)
        kind = rnd.choice(["core", "core", "core_trained", "core_graduate", "champion"])
        # Every seventh school is a Champion candidate by the official rule
        # (or a near miss), which random records would rarely make.
        candidate = n % 7 == 0 and bool(code)
        if candidate:
            kind = rnd.choice(["core", "core_trained"])
        row = {
            "id": sid, "code": code,
            "name": rnd.choice(names) if rnd.random() < 0.5 else f"School {rnd.randint(1, 99):02d}",
            "type": kind, "district": rnd.choice(["Mukono", "Wakiso", "", "Jinja"]),
            "cluster_id": rnd.choice(["cl1", "cl2", "cl3", "gone", ""]),
            "owner_id": rnd.choice(["own-1", "u-own-1", "own-2", "own-3", "departed", ""]),
            "sub_region_id": rnd.choice(["sr1", "sr2", "", "sr-gone"]),
        }  # fmt: skip
        world["schools"].append({**row, "created": created + timedelta(hours=n)})
        rec["countries"][sid] = rnd.choice(["Uganda", "Uganda", "Kenya", ""])
        quality = rnd.random()
        # SSA records: the year's, last year's and older, a few without an
        # average of their own.
        for year in (fy, previous, str(int(fy) - 2)):
            for k in range(
                1 if candidate and year == fy else rnd.choice([0, 1, 1, 1, 2])
            ):
                record_no += 1
                start = date(int(year) - 1, 10, 1)
                taken = start + timedelta(days=rnd.randint(0, 300) + k * 3)
                scores = {}
                base = rnd.uniform(2, 9.5) + (quality if year == fy else 0)
                for area in rnd.sample(AREAS, len(AREAS)):
                    if candidate:
                        scores[area] = rnd.choice(
                            [
                                rnd.uniform(7.0, 9.9),
                                7.0,
                                9.5,
                                6.99 if rnd.random() < 0.1 else 8.0,
                            ]
                        )
                    elif rnd.random() < 0.9:
                        scores[area] = min(
                            10.0,
                            max(
                                0.0,
                                rnd.choice(
                                    [
                                        base + rnd.uniform(-2.5, 2.5),
                                        round(base, 1),
                                        5.0,
                                        8.0,
                                        4.99,
                                    ]
                                ),
                            ),
                        )
                if rnd.random() < 0.05:
                    scores["new_area_2028"] = rnd.uniform(1, 9)
                average = rnd.choice(
                    [
                        None,
                        sum(scores.values()) / len(scores) if scores else None,
                        6.125,
                        8.0,
                        8.3,
                    ]
                )
                if candidate:
                    average = rnd.choice([8.3, 8.0, 9.1, 7.95])
                world["ssa"].append({
                    "id": f"r{record_no:04d}", "school_id": sid, "code": code, "fy": year,
                    "taken": datetime.combine(taken, datetime.min.time(), timezone.utc) + timedelta(hours=rnd.choice([0, 22])),
                    "created": created + timedelta(minutes=record_no), "average": average, "scores": scores,
                })  # fmt: skip
        # The year's plan, under the school's id or its School ID.
        if candidate or rnd.random() < 0.75:
            vt, tt = rnd.choice([(4, 4), (4, 4), (0, 0), (2, 4)])
            rec["plans"].append({
                "school_key": rnd.choice([sid, code or sid]),
                "visits_done": rnd.randint(0, vt + 1), "visits_target": vt,
                "trainings_done": rnd.randint(0, tt + 1), "trainings_target": tt,
            })  # fmt: skip
            if rnd.random() < 0.1:
                rec["plans"].append(
                    {
                        "school_key": sid,
                        "visits_done": 4,
                        "visits_target": 4,
                        "trainings_done": 4,
                        "trainings_target": 4,
                    }
                )
        if rnd.random() < 0.3:
            rec["handovers"].append(
                {
                    "school_id": sid,
                    "assigned": rnd.randint(0, 2),
                    "scheduled": rnd.randint(0, 2),
                    "completed": rnd.randint(0, 1),
                }
            )
        for _ in range(rnd.randint(0, 4)):
            rec["register"].append({
                "school_id": sid, "invited": rnd.random() < 0.85, "attended": rnd.random() < 0.6,
                "teachers": rnd.choice([None, 0, 2, 5]), "leaders": rnd.choice([None, 1, 3]),
            })  # fmt: skip
        for _ in range(rnd.choice([0, 0, 1, 2])):
            rec["trainings"].append(
                {
                    "school_id": sid,
                    "teachers": rnd.choice([None, 4, 9]),
                    "leaders": rnd.choice([None, 0, 2]),
                }
            )
        before = rnd.choice([None, 0, rnd.randint(40, 900)])
        if before is not None:
            rec["enrolment"].append(
                {"school_id": sid, "fy": previous, "enrollment": before}
            )
        if rnd.random() < 0.8:
            rec["enrolment"].append(
                {
                    "school_id": sid,
                    "fy": fy,
                    "enrollment": max(0, (before or 100) + rnd.randint(-80, 160)),
                }
            )
        for year in (previous, fy):
            for _ in range(rnd.randint(0, 3)):
                top = rnd.choice([50, 100, 500])
                rec["learning"].append({
                    "school_id": sid, "fy": year, "mean": round(rnd.uniform(0.2, 0.95) * top, 2),
                    "max": float(top), "learners": rnd.choice([0, 8, 31, 80]),
                })  # fmt: skip
        # The Core profile and the Champion rule's inputs.
        if candidate or (code and rnd.random() < 0.85):
            status = rnd.choice(
                [
                    None,
                    "Not Eligible",
                    "Potential Champion",
                    "Champion",
                    "Approved Champion",
                    "Not Eligible",
                ]
            )
            if candidate:
                status = rnd.choice([None, "Potential Champion", "Not Eligible"])
            rec["stored"].append({"code": code, "status": status})
            rec["scan_profiles"].append(code)
            if candidate:
                rec["scan_plans"].append(
                    {
                        "code": code,
                        "fy": operational,
                        "total": 8,
                        "completed": rnd.choice([8, 8, 9, 7]),
                    }
                )
            for year in rnd.sample(
                [fy, operational, previous, "2025"], rnd.randint(0, 3)
            ):
                if not any(
                    p["code"] == code and p["fy"] == year for p in rec["scan_plans"]
                ):
                    total = rnd.choice([8, 8, 0, 9])
                    rec["scan_plans"].append(
                        {
                            "code": code,
                            "fy": year,
                            "total": total,
                            "completed": rnd.choice([0, 3, 8, min(total, 8)]),
                        }
                    )
            if candidate or rnd.random() < 0.9:
                closed = rnd.choice([0, 2, 5])
                rec["scan_schools"].append(
                    {"code": code, "closed": closed, "clean": rnd.randint(0, closed)}
                )
        for k, area in enumerate(rnd.sample(AREAS, rnd.randint(0, 3))):
            world["recs"].append({
                "school_id": sid, "intervention": area if rnd.random() < 0.95 else "retired_area", "rank": k,
                "score": rnd.choice([None, "6.10", "4.25", "7.05", "3.95"]),
                "band": rnd.choice(["", "Improving", "Critical"]),
                "reason": rnd.choice(["", "  ", f"{area} scored low twice."]), "state": rnd.choice(STATES),
                # The recommended training, or why none is mapped: from the
                # position, so the seeded stream (and every other record) is
                # unchanged.
                "item": ["Business Planning Support", "", ""][(k + len(area)) % 3],
                "has_item": (k + len(area)) % 3 == 0,
                "unmapped": ["", "No course covers it", ""][(k + len(area)) % 3],
            })  # fmt: skip
    # The statements' orders.
    world["schools"].sort(key=lambda s: s["created"], reverse=True)
    rec["schools"] = [
        {k: v for k, v in s.items() if k != "created"} for s in world["schools"]
    ]
    confirmed = world["ssa"]
    two_years = sorted(
        (r for r in confirmed if r["fy"] in (fy, previous)),
        key=lambda r: (
            r["school_id"],
            r["fy"],
            -r["taken"].timestamp(),
            -r["created"].timestamp(),
            r["id"],
        ),
    )
    rec["year_records"] = [
        {
            "id": r["id"],
            "school_id": r["school_id"],
            "fy": r["fy"],
            "average": r["average"],
        }
        for r in two_years
    ]
    seen = set()
    for r in two_years:
        if (r["school_id"], r["fy"]) in seen:
            continue
        seen.add((r["school_id"], r["fy"]))
        if r["average"] is None:
            rec["year_carried"] += [
                {"record_id": r["id"], "intervention": a, "score": s}
                for a, s in r["scores"].items()
            ]
    this_year = sorted(
        (r for r in confirmed if r["fy"] == fy),
        key=lambda r: (
            r["school_id"],
            -r["taken"].timestamp(),
            -r["created"].timestamp(),
        ),
    )
    rec["current_records"] = [
        {"id": r["id"], "school_id": r["school_id"], "fy": fy, "average": r["average"]}
        for r in this_year
    ]
    latest_now, latest_before = {}, {}
    for r in this_year:
        latest_now.setdefault(r["school_id"], r)
    last_year = sorted(
        (r for r in confirmed if r["fy"] == previous),
        key=lambda r: (
            r["school_id"],
            -r["taken"].timestamp(),
            -r["created"].timestamp(),
        ),
    )
    for r in last_year:
        if r["school_id"] in latest_now:
            latest_before.setdefault(r["school_id"], r)
    for r in latest_now.values():
        rec["current_scores"] += [
            {"record_id": r["id"], "intervention": a, "score": s}
            for a, s in r["scores"].items()
        ]
    rec["latest_now"] = [
        {
            "school_id": s,
            "record_id": r["id"],
            "taken_on": r["taken"].date().isoformat(),
        }
        for s, r in sorted(latest_now.items())
    ]
    rec["latest_before"] = [
        {
            "school_id": s,
            "record_id": r["id"],
            "taken_on": r["taken"].date().isoformat(),
        }
        for s, r in sorted(latest_before.items())
    ]
    for s, r in latest_now.items():
        if s in latest_before:
            for one in (r, latest_before[s]):
                rec["pair_scores"] += [
                    {"record_id": one["id"], "intervention": a, "score": v}
                    for a, v in one["scores"].items()
                ]
    rnd.shuffle(rec["current_scores"])
    rnd.shuffle(rec["pair_scores"])
    rnd.shuffle(rec["learning"])
    rec["scan_plans"].sort(key=lambda p: (p["code"], -int(p["fy"])))
    profiled = set(rec["scan_profiles"])
    for r in sorted(
        (r for r in confirmed if r["code"] in profiled),
        key=lambda r: (r["code"], r["taken"], r["created"]),
    ):
        rec["scan_ssas"].append(
            {"id": r["id"], "code": r["code"], "average": r["average"]}
        )
    last = {}
    for r in rec["scan_ssas"]:
        last[r["code"]] = r["id"]
    by_id = {r["id"]: r for r in confirmed}
    for record_id in last.values():
        rec["scan_scores"] += [
            {"record_id": record_id, "score": v}
            for v in by_id[record_id]["scores"].values()
        ]
    world["recs"].sort(key=lambda r: (r["school_id"], r["rank"], r["intervention"]))
    rec["recommendations"] = [
        {k: v for k, v in r.items() if k != "rank"} for r in world["recs"]
    ]
    if rules:
        rec["change_rules"] = [
            {"intervention": "leadership", "country": "", "direction": "improve", "threshold": 0.5},
            {"intervention": "leadership", "country": " Kenya ", "direction": "", "threshold": -0.25},
            {"intervention": "enrolment", "country": "", "direction": "maintain_strong", "threshold": None},
            {"intervention": "financial_health", "country": "Uganda", "direction": "improve", "threshold": 0.3},
            {"intervention": "", "country": "", "direction": "improve", "threshold": 5.0},
        ]  # fmt: skip
    return rec, world


def answer(rec, world, user, query, operational):
    """The existing application's page for ``rec``, read by ``user``."""
    district = lambda name: NS(name=name) if name else None  # noqa: E731
    schools = [
        NS(
            id=s["id"], school_id=s["code"], name=s["name"], school_type=s["type"],
            get_school_type_display=(lambda t=s["type"]: TYPES.get(t, t)),
            district=district(s["district"]), cluster_id=s["cluster_id"] or None,
            account_owner_id=s["owner_id"] or None, sub_region_id=s["sub_region_id"] or None,
        )
        for s in rec["schools"]
    ]  # fmt: skip
    people = {}
    for key, label in rec["owners"].items():
        people[key] = NS(
            user=NS(
                name=label if "@" not in label and label != "Unnamed" else "",
                email=label if "@" in label else "",
            )
        )

    def ssa_records(calls):
        values = called(calls, "values")[0][1]
        if "school__school_id" in values:
            return [
                {
                    "id": r["id"],
                    "school__school_id": r["code"],
                    "date_of_ssa": None,
                    "average_score": r["average"],
                }
                for r in rec["scan_ssas"]
            ]
        if "fy" in values:
            return [
                {
                    "id": r["id"],
                    "school_id": r["school_id"],
                    "fy": r["fy"],
                    "average_score": r["average"],
                }
                for r in rec["year_records"]
            ]
        return [
            {"id": r["id"], "school_id": r["school_id"], "average_score": r["average"]}
            for r in rec["current_records"]
        ]

    def ssa_scores(calls):
        if called(calls, "values"):
            return [
                {
                    "ssa_record_id": r["record_id"],
                    "score": r["score"],
                    "intervention": "",
                }
                for r in rec["scan_scores"]
            ]
        fields = called(calls, "values_list")[0][1]
        if len(fields) == 2:
            return [(r["record_id"], r["score"]) for r in rec["year_carried"]]
        if kw(calls, "score__isnull") is False:
            return [
                (r["record_id"], r["intervention"], r["score"])
                for r in rec["current_scores"]
            ]
        return [
            (r["record_id"], r["intervention"], r["score"]) for r in rec["pair_scores"]
        ]

    def school_rows(calls):
        if called(calls, "values_list"):
            return [(sid, country or None) for sid, country in rec["countries"].items()]
        return [
            NS(
                school_id=s["code"],
                champion_closed_count=s["closed"],
                champion_clean_evidence_count=s["clean"],
            )
            for s in rec["scan_schools"]
        ]

    def plans(calls):
        if called(calls, "values"):
            return [
                {
                    "school_id": p["code"],
                    "fy": p["fy"],
                    "champion_total_slots": p["total"],
                    "champion_completed_slots": p["completed"],
                }
                for p in rec["scan_plans"]
            ]
        return [NS(school_id=p["school_key"], visits_completed=p["visits_done"], visits_target=p["visits_target"],
                   trainings_completed=p["trainings_done"], trainings_target=p["trainings_target"]) for p in rec["plans"]]  # fmt: skip

    def profiles(calls):
        if called(calls, "values_list"):
            return [(p["code"], p["status"]) for p in rec["stored"]]
        return [NS(school_id=code) for code in rec["scan_profiles"]]

    def recommendations(calls):
        shown = set(kw(calls, "school_id__in") or [])
        states = {str(s) for s in (kw(calls, "state__in") or [])}
        return [
            NS(school_id=r["school_id"], rank=0, intervention=r["intervention"], score=Decimal(r["score"]) if r["score"] else None,
               score_band=r["band"], reason=r["reason"],
               recommended_item=NS(display_name=r["item"]) if r["has_item"] else None, unmapped_reason=r["unmapped"],
               get_intervention_display=(lambda v=r["intervention"]: dict(SsaIntervention.choices).get(v, v)),
               get_state_display=(lambda v=r["state"]: STATE_LABELS[v]))
            for r in rec["recommendations"]
            if r["school_id"] in shown and r["state"] in states
        ]  # fmt: skip

    day = date.fromisoformat
    latest = {}
    for key, rows in (("now", rec["latest_now"]), ("before", rec["latest_before"])):
        latest[key] = {
            r["school_id"]: (r["record_id"], day(r["taken_on"])) for r in rows
        }

    def latest_records(ids, year):
        which = latest["now"] if str(year) == fy_of[0] else latest["before"]
        wanted = set(ids)
        return {sid: v for sid, v in which.items() if sid in wanted}

    fy_of = [
        core_oversight_views._choice(
            NS(GET=query), "fy", sorted(fy_options(), reverse=True), operational
        )
    ]
    rule_rows = [
        NS(
            id=f"rule-{i}", intervention=r["intervention"], country=r["country"], version=i + 1,
            expected_direction=r["direction"],
            min_meaningful_change=None if r["threshold"] is None else Decimal(str(r["threshold"])),
        )
        for i, r in enumerate(rec["change_rules"])
    ]  # fmt: skip
    learning = [
        {"school_id": r["school_id"], "fy": r["fy"], "mean_score": Decimal(str(r["mean"])),
         "max_score": Decimal(str(r["max"])), "learners_tested": r["learners"]}
        for r in rec["learning"]
    ]  # fmt: skip
    statements = [
        mock.patch.object(intelligence, "scoped_core_schools", lambda principal: schools),
        mock.patch.object(oversight_service, "_staff_directory", lambda ids: {k: v for k, v in people.items() if k in ids}),
        mock.patch.object(Cluster, "objects", Fake(lambda c: list(rec["clusters"].items()))),
        mock.patch.object(SubRegion, "objects", Fake(lambda c: list(rec["sub_regions"].items()))),
        mock.patch.object(SsaRecord, "objects", Fake(ssa_records)),
        mock.patch.object(SsaScore, "objects", Fake(ssa_scores)),
        mock.patch.object(School, "objects", Fake(school_rows)),
        mock.patch.object(impact_engine, "_latest_confirmed_records", latest_records),
        mock.patch.object(change_rules, "_published_rows", lambda **kw: Fake(lambda c: rule_rows)),
        mock.patch.object(package_split, "package_splits", lambda schools, fy: {}),
        mock.patch.object(CorePlan, "objects", Fake(plans)),
        mock.patch.object(PartnerAssignment, "objects", Fake(lambda c: [dict(r) for r in rec["handovers"]])),
        mock.patch.object(ClusterActivityAttendance, "objects", Fake(
            lambda c: [(r["invited"], r["attended"], r["school_id"], r["teachers"], r["leaders"]) for r in rec["register"]])),
        mock.patch.object(Activity, "objects", Fake(
            lambda c: [(r["school_id"], r["teachers"], r["leaders"]) for r in rec["trainings"]])),
        mock.patch.object(SchoolEnrollmentHistory, "objects", Fake(
            lambda c: [(r["school_id"], r["fy"], r["enrollment"]) for r in rec["enrolment"]])),
        mock.patch.object(LearningAssessmentResult, "objects", Fake(lambda c: learning)),
        mock.patch.object(CoreSchoolProfile, "objects", Fake(profiles)),
        mock.patch.object(SsaRecommendation, "objects", Fake(recommendations)),
        mock.patch.object(champion_services, "get_operational_fy", lambda: operational),
        mock.patch.object(core_oversight_views, "get_operational_fy", lambda: operational),
    ]  # fmt: skip
    for patch in statements:
        patch.start()
    try:
        status, body = read_page(
            user, "/core-schools-oversight/", dict(sorted(query.items()))
        )
    finally:
        for patch in reversed(statements):
            patch.stop()
    if status != 200:
        raise RuntimeError(f"the page answered {status}: {body}")
    return body, fy_of[0]


def reader(email, role=None):
    """A seeded account, working in ``role`` for this reading only (nothing
    is saved)."""
    user = get_user_model().objects.get(email=email)
    if role:
        user.active_role = role
        user.roles = [role]
    return user


def main():
    cases = []

    def case(name, made, user, query=None, operational="2027"):
        rec, world = made
        query = query or {}
        body, fy = answer(rec, world, user, query, operational)
        cases.append(
            {
                "name": name, "role": user.active_role, "fy": fy,
                "years": sorted(fy_options(), reverse=True), "operational": operational,
                "query": query, "records": rec, "body": body,
            }
        )  # fmt: skip

    officer = reader("cceo@edify.org")
    rich = make(11, schools=40)
    case("an officer reads every figure", rich, officer)
    for tab in ("groups", "attention", "recommendations", "champion"):
        case(f"the {tab} tab", rich, officer, {"tab": tab})
    for group in ("district", "sub_region", "cluster"):
        case(f"groups by {group}", rich, officer, {"tab": "groups", "group": group})
    for sort in ("latest", "change", "package", "attendance"):
        case(f"sorted by {sort}", rich, officer, {"sort": sort})
    rvp = reader("cceo1@edify.org", "RegionalVicePresident")
    case("a Regional Vice President is given no school links", rich, rvp)
    case("a Regional Vice President's attention list", rich, rvp, {"tab": "attention"})
    case("a Regional Vice President's Champion list", rich, rvp, {"tab": "champion"})
    case(
        "a Regional Programme Lead's recommendations",
        rich,
        reader("cceo1@edify.org", "RegionalProgramLead"),
        {"tab": "recommendations"},
    )
    case("filters with stray spaces", rich, officer,
         {"trajectory": " declined ", "district": " Mukono ", "type": " core ", "q": "  KIMEN "})  # fmt: skip
    case("filters that are values", rich, officer,
         {"trajectory": "improved", "attention": "Package incomplete", "readiness": "Progressing", "district": "Wakiso"})  # fmt: skip
    case("a search by School ID", rich, officer, {"q": "101"})
    case(
        "the fallback where no rule is published",
        make(12, schools=30, rules=False),
        officer,
    )
    for seed in (21, 22, 23):
        made = make(seed, schools=35)
        case(f"more schools ({seed})", made, reader("cd@edify.org"))
        case(
            f"more schools ({seed}), Champion readiness",
            made,
            officer,
            {"tab": "champion"},
        )
        case(
            f"more schools ({seed}), recommendations",
            made,
            officer,
            {"tab": "recommendations"},
        )
    case(
        "last year, with this year's live plans",
        make(31, schools=30, fy="2026"),
        officer,
        {"fy": "2026"},
    )
    case(
        "a plan in the running year speaks for a school",
        make(32, schools=30, operational="2026"),
        officer,
        operational="2026",
    )
    many = make(41, schools=130)
    case("the first of three pages", many, officer)
    case(
        "a second page keeps the query",
        many,
        officer,
        {"page": "2", "sort": "latest", "trajectory": "not_comparable"},
    )
    case("a page past the last is the last", many, officer, {"page": "99"})
    case("a page that is not a number", many, officer, {"page": "two"})
    case("eight pages make a gap", make(42, schools=420), officer, {"page": "4"})
    case("a group of many", many, officer, {"tab": "groups"})
    case("nothing in scope", make(51, schools=0), officer)
    case(
        "nothing in scope, attention",
        make(51, schools=0),
        officer,
        {"tab": "attention"},
    )
    case(
        "nothing in scope, recommendations",
        make(51, schools=0),
        officer,
        {"tab": "recommendations"},
    )
    text = json.dumps(cases, ensure_ascii=False, separators=(",", ":"), default=str)
    with (
        OUT.open("wb") as raw,
        gzip.GzipFile(fileobj=raw, mode="wb", mtime=0) as packed,
    ):
        packed.write(text.encode("utf-8"))
    print(f"Wrote {OUT}: {len(cases)} cases")


main()
