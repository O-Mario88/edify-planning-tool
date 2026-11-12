"""Write golden.json.gz: Cluster Oversight as the existing application answers
it for records the development seed does not hold.

    python manage.py shell < platform/backend/internal/clusteroversight/testdata/golden.py

Each case is a set of records as the page's statements would return them
(made here from a seeded random source, so every rule the Command Center
applies is reached: registers and the older attendance lists, schools
drifting away, SSA pairs judged by published rules and by the fallback,
readings too close to compare, enrolment and learning, loans, change
stories, the session plan, stored weights, and a table of more than one
page), the reader, and the page the existing application's own code makes
of them: apps.clusters.workspace, scores, profile_insights, outcomes,
apps.ssa.change_rules and year_comparison, the page's view and template, and
the app's feed reader, all unmodified. Only the statements themselves are
stood in for, so nothing is read from or written to the database beyond the
reader's own account. page_golden_test.go gives the same records to Go and
expects the same page.
"""

import gzip
import json
import random
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace as NS
from unittest import mock

from django.contrib.auth import get_user_model

from apps.accounts.models import User
from apps.activities.models import Activity, ClusterActivityAttendance
from apps.analytics import impact_engine
from apps.business_transformation.models import MfiLoan
from apps.clusters import outcomes, oversight_service, workspace
from apps.clusters import profile_insights as insights
from apps.clusters.models import ClusterScoreSetting
from apps.core import scoping
from apps.core.enums import SsaIntervention
from apps.core.fy import fy_options
from apps.impact.models import LearningAssessmentResult
from apps.mobile_feed.views import read_page
from apps.schools.models import School, SchoolEnrollmentHistory
from apps.ssa import change_rules, year_comparison
from apps.ssa.models import SsaRecord, SsaScore
from apps.targets.models import MostSignificantChangeStory

OUT = Path("platform/backend/internal/clusteroversight/testdata/golden.json.gz")
TODAY = date(2026, 11, 12)
AREAS = [i.value for i in SsaIntervention]
MEETINGS = ("cluster_meeting", "cluster_meeting_ssa_review")
TRAININGS = ("cluster_training", "cluster_training_ssa_collection")
DELIVERED = ("completed", "ia_verified", "closed", "submitted_to_pl")


def iso(day):
    return day.isoformat() if day else ""


def chain(result):
    """A manager whose every call returns itself and which iterates as
    ``result``: any chain of filter / exclude / values / order_by."""
    manager = mock.MagicMock()
    for name in (
        "filter", "exclude", "values", "values_list", "order_by", "distinct",
        "select_related", "only", "annotate",
    ):  # fmt: skip
        getattr(manager, name).return_value = manager
    manager.__iter__.side_effect = lambda: iter(result)
    manager.first.return_value = result[0] if result else None
    return manager


def make(seed, *, clusters, mine=(), setting=None, rules=True):
    """One set of records. ``mine`` are owner ids given to the first clusters
    in turn (the reader's own, for My Clusters)."""
    # Made-up records for a test, repeatable from the seed: not a secret.
    rnd = random.Random(seed)  # nosec B311
    rec = {
        "clusters": [], "owners": {}, "members": [], "sessions": [], "register": [],
        "latest_now": [], "latest_before": [], "pair_scores": [], "change_rules": [],
        "enrolment": [], "learning": [], "funded": [], "stories": [], "plan": [],
        "setting": setting, "year_records": [], "year_scores": [], "last_delivered": {},
    }  # fmt: skip
    owners = {"own-1": "Grace A.", "own-2": "paul@example.org", "own-3": "Unnamed"}
    rec["owners"] = dict(owners)
    record_no = 0
    for n in range(clusters):
        cid = f"cl{n:03d}"
        quality = rnd.random() if n else 1.0
        owner = rnd.choice(["own-1", "own-2", "own-3", " own-1 ", "gone", "", None])
        if n < len(mine):
            owner = mine[n]
        rec["clusters"].append(
            {
                "id": cid,
                "name": f"Cluster {n:03d}" if n != 2 else "  Cluster   002  spaced ",
                "district": rnd.choice(["Mukono", "Wakiso", "Jinja"]),
                "owner_id": owner,
                "leader_name": rnd.choice(
                    [None, "", "  ", "Jane  Nakato", "Okello P."]
                ),
                "leader_phone": rnd.choice([None, "", "0772 000 001"]),
            }
        )
        schools = []
        size = 0 if n in (1, 7) or clusters > 20 else rnd.randint(1, 7)
        for k in range(size):
            sid = f"s{n:03d}{k}"
            schools.append(sid)
            rec["members"].append(
                {"id": sid, "cluster_id": cid, "country": rnd.choice(["Uganda", "Uganda", "Kenya", ""])}
            )  # fmt: skip
        # Sessions: this year's and last year's, with a register, with the
        # older list of who came, or with neither.
        held = []
        for k in range(rnd.randint(0, 12) if size else rnd.randint(0, 1)):
            aid = f"a{n:03d}{k}"
            training = rnd.random() < 0.45
            fy = rnd.choice(["2027", "2027", "2026", "2025"])
            start = {
                "2027": date(2026, 10, 1),
                "2026": date(2025, 10, 1),
                "2025": date(2024, 10, 1),
            }[fy]
            planned = start + timedelta(days=rnd.randint(0, 40))
            actual = rnd.choice([None, planned, planned + timedelta(days=2)])
            if rnd.random() < 0.08:
                planned = actual = None
            register_kind = rnd.choice(
                ["register", "register", "legacy", "both", "none"]
            )
            came_named = []
            for sid in schools:
                attends = rnd.random() < 0.05 + 0.95 * quality
                if register_kind in ("register", "both") and rnd.random() < 0.9:
                    rec["register"].append(
                        {"activity_id": aid, "school_id": sid, "invited": rnd.random() < 0.9, "attended": attends}
                    )  # fmt: skip
                if (
                    register_kind in ("legacy", "both")
                    and attends
                    and rnd.random() < 0.7
                ):
                    came_named.append(sid)
            if register_kind != "none" and rnd.random() < 0.2:
                # A guest from another cluster.
                rec["register"].append(
                    {"activity_id": aid, "school_id": "guest-school", "invited": False, "attended": True}
                )  # fmt: skip
            rec["sessions"].append(
                {
                    "id": aid, "cluster_id": cid,
                    "type": rnd.choice(TRAININGS if training else MEETINGS),
                    "fy": fy,
                    "focus": rnd.choice(AREAS + ["", "", "overall", "not_an_area"]) if training else "",
                    "attended": came_named,
                    "held_on": iso(actual or planned),
                }
            )  # fmt: skip
            held.append(actual or planned)
        if any(held) and rnd.random() < 0.9:
            rec["last_delivered"][cid] = iso(max(d for d in held if d))
        # The plan for the year.
        for k in range(rnd.randint(0, 5) if rnd.random() < 0.4 + 0.6 * quality else 0):
            status = rnd.choice(
                DELIVERED + ("scheduled", "scheduled", "approved", "returned")
            )
            if quality == 1.0:
                status = "ia_verified"
            planned = rnd.choice(
                [None, TODAY, TODAY - timedelta(days=9), TODAY + timedelta(days=1), TODAY + timedelta(days=40)]
            )  # fmt: skip
            rec["plan"].append(
                {
                    "cluster_id": cid,
                    "type": rnd.choice(MEETINGS + TRAININGS) if quality < 1 else (MEETINGS + TRAININGS)[k % 4],
                    "status": status,
                    "planned": iso(planned),
                }
            )  # fmt: skip
        for sid in schools:
            # SSA: the latest confirmed record of each year and its scores.
            has_now, has_before = rnd.random() < 0.85, rnd.random() < 0.8
            taken_before = date(2026, 3, 1) + timedelta(days=rnd.randint(0, 150))
            taken_now = taken_before + timedelta(
                days=rnd.choice([30, 119, 120, 121, 200, 240])
            )
            scored_now, scored_before = {}, {}
            for area in rnd.sample(AREAS, len(AREAS)):
                if rnd.random() < 0.9:
                    scored_before[area] = rnd.choice(
                        [rnd.uniform(1, 9.5), round(rnd.uniform(1, 9.5), 1), 5.0, 8.0]
                    )
                if rnd.random() < 0.9:
                    drift = (
                        rnd.uniform(-1.5, 2.5) * (0.3 + quality)
                        if rnd.random() < 0.85
                        else 0.0
                    )
                    base = scored_before.get(area, rnd.uniform(2, 9))
                    scored_now[area] = min(
                        10.0,
                        max(0.0, rnd.choice([base + drift, round(base + drift, 1)])),
                    )
            if has_now:
                record_no += 1
                now_id = f"r{record_no:04d}"
                rec["latest_now"].append(
                    {"school_id": sid, "record_id": now_id, "taken_on": iso(taken_now)}
                )
                average = rnd.choice(
                    [
                        None,
                        sum(scored_now.values()) / len(scored_now)
                        if scored_now
                        else None,
                        6.125,
                    ]
                )
                rec["year_records"].append(
                    {"id": now_id, "school_id": sid, "average": average}
                )
                if rnd.random() < 0.2:
                    # An older record of the same year, which is not read.
                    rec["year_records"].append(
                        {"id": now_id + "-old", "school_id": sid, "average": 1.0}
                    )
                for area, score in scored_now.items():
                    rec["year_scores"].append(
                        {"record_id": now_id, "intervention": area, "score": score}
                    )
                if rnd.random() < 0.04:
                    rec["year_scores"].append(
                        {
                            "record_id": now_id,
                            "intervention": "new_area_2028",
                            "score": rnd.uniform(0.2, 9),
                        }
                    )
            if has_before:
                record_no += 1
                before_id = f"r{record_no:04d}"
                rec["latest_before"].append(
                    {
                        "school_id": sid,
                        "record_id": before_id,
                        "taken_on": iso(taken_before),
                    }
                )
            if has_now and has_before:
                for area, score in scored_now.items():
                    rec["pair_scores"].append(
                        {"record_id": now_id, "intervention": area, "score": score}
                    )
                for area, score in scored_before.items():
                    rec["pair_scores"].append(
                        {"record_id": before_id, "intervention": area, "score": score}
                    )
            # Enrolment in the two years.
            before = rnd.choice([None, 0, rnd.randint(40, 900)])
            if before is not None:
                rec["enrolment"].append(
                    {"school_id": sid, "fy": "2026", "enrollment": before}
                )
            if rnd.random() < 0.8:
                grown = (before or 100) + int(rnd.randint(-60, 160) * (0.2 + quality))
                rec["enrolment"].append(
                    {"school_id": sid, "fy": "2027", "enrollment": max(0, grown)}
                )
            # Learning results: several classes a year.
            for fy in ("2026", "2027"):
                for _ in range(rnd.randint(0, 3)):
                    top = rnd.choice([50, 100, 500])
                    rec["learning"].append(
                        {
                            "school_id": sid, "fy": fy,
                            "mean": round(rnd.uniform(0.2, 0.9 + (0.1 * quality if fy == "2027" else 0)) * top, 2),
                            "max": float(top),
                            "learners": rnd.choice([0, 8, 31, 80]),
                        }
                    )  # fmt: skip
            for _ in range(rnd.choice([0, 0, 0, 1, 2]) if quality < 1 else 1):
                rec["funded"].append(sid)
            for _ in range(rnd.choice([0, 0, 0, 1])):
                rec["stories"].append(
                    {"cluster_id": rnd.choice(["", "elsewhere"]), "school_id": sid,
                     "status": rnd.choice(["approved", "submitted", "returned", "rejected", "archived"])}
                )  # fmt: skip
        for _ in range(rnd.choice([0, 0, 1, 3]) if quality < 1 else 3):
            rec["stories"].append(
                {"cluster_id": cid, "school_id": "",
                 "status": rnd.choice(["approved", "submitted"]) if quality < 1 else "approved"}
            )  # fmt: skip
    rec["stories"].append(
        {"cluster_id": "elsewhere", "school_id": "unknown", "status": "approved"}
    )
    rec["latest_now"].sort(key=lambda r: r["school_id"])
    rec["latest_before"].sort(key=lambda r: r["school_id"])
    rec["year_records"].sort(key=lambda r: (r["school_id"], r["id"].endswith("-old")))
    rnd.shuffle(rec["year_scores"])
    rnd.shuffle(rec["pair_scores"])
    rnd.shuffle(rec["learning"])
    if rules:
        rec["change_rules"] = [
            # Newest first: the first row read for a key speaks for it.
            {"intervention": "leadership", "country": "", "direction": "improve", "threshold": 0.5},
            {"intervention": "leadership", "country": "", "direction": "improve", "threshold": 9.0},
            {"intervention": "leadership", "country": " Kenya ", "direction": "", "threshold": -0.25},
            {"intervention": "enrolment", "country": "", "direction": "maintain_strong", "threshold": None},
            {"intervention": "financial_health", "country": "Uganda", "direction": "improve", "threshold": 0.3},
            {"intervention": "learning_environment", "country": "", "direction": "improve", "threshold": None},
            {"intervention": "", "country": "", "direction": "improve", "threshold": 5.0},
        ]  # fmt: skip
    return rec


def answer(rec, user, fy, query):
    """The existing application's page for ``rec``, read by ``user``."""
    members = {c["id"]: [] for c in rec["clusters"]}
    for m in rec["members"]:
        members[m["cluster_id"]].append(
            {"id": m["id"], "school_id": "ID-" + m["id"], "name": m["id"],
             "cluster_id": m["cluster_id"], "region__country": m["country"] or None}
        )  # fmt: skip
    clusters = [
        NS(
            id=c["id"], name=c["name"], district=NS(name=c["district"]),
            responsible_staff_id=c["owner_id"], cluster_leader_name=c["leader_name"],
            cluster_leader_phone=c["leader_phone"],
        )
        for c in rec["clusters"]
    ]  # fmt: skip
    labels = {
        "Grace A.": NS(user=NS(name="Grace A.", email="grace@example.org")),
        "paul@example.org": NS(user=NS(name="", email="paul@example.org")),
        "Unnamed": NS(user=NS(name="", email="")),
    }
    directory = {key: labels[label] for key, label in rec["owners"].items()}
    day = date.fromisoformat
    sessions = [
        NS(
            id=s["id"], cluster_id=s["cluster_id"], activity_type=s["type"], fy=s["fy"],
            focus_intervention=s["focus"] or None, attended_school_ids=list(s["attended"]),
            actual_delivery_date=day(s["held_on"]) if s["held_on"] else None, planned_date=None,
            responsible_staff_id=None, training_course_id=None, catalogue_item=None,
            get_activity_type_display=lambda: "Cluster Meeting",
        )
        for s in rec["sessions"]
    ]  # fmt: skip
    register = [{**r, "teachers": 1, "leaders": None} for r in rec["register"]]
    latest = {
        fy: {
            r["school_id"]: (r["record_id"], day(r["taken_on"]))
            for r in rec["latest_now"]
        },
        str(int(fy) - 1): {
            r["school_id"]: (r["record_id"], day(r["taken_on"]))
            for r in rec["latest_before"]
        },
    }
    rule_rows = [
        NS(
            id=f"rule-{i}", intervention=r["intervention"], country=r["country"], version=i + 1,
            expected_direction=r["direction"],
            min_meaningful_change=None if r["threshold"] is None else Decimal(str(r["threshold"])),
        )
        for i, r in enumerate(rec["change_rules"])
    ]  # fmt: skip
    pair_scores = chain(
        [(s["record_id"], s["intervention"], s["score"]) for s in rec["pair_scores"]]
    )
    year_scores = chain(
        [(s["record_id"], s["intervention"], s["score"]) for s in rec["year_scores"]]
    )
    scores = mock.MagicMock()
    scores.filter.side_effect = (
        lambda *a, **kw: year_scores if "score__isnull" in kw else pair_scores
    )
    stories = [
        NS(
            id=f"story-{i}", cluster_id=s["cluster_id"] or None, school_id=s["school_id"] or None,
            status=s["status"], user_id="u", title="t", story_date=TODAY, intervention="",
            evidence_uri="", school=NS(school_id="", name=""), get_status_display=lambda: "",
        )
        for i, s in enumerate(rec["stories"])
    ]  # fmt: skip
    setting = rec["setting"] and NS(
        health_weights=rec["setting"]["health"], impact_weights=rec["setting"]["impact"],
        teacher_weights=rec["setting"]["teacher"], leader_weights=rec["setting"]["leader"],
        maturity_rules=rec["setting"]["maturity"], set_by="", created_at=None,
    )  # fmt: skip
    plan = [
        {"cluster_id": p["cluster_id"], "activity_type": p["type"], "status": p["status"],
         "planned_date": day(p["planned"]) if p["planned"] else None}
        for p in rec["plan"]
    ]  # fmt: skip
    learning = [
        {"school_id": r["school_id"], "fy": r["fy"], "mean_score": Decimal(str(r["mean"])),
         "max_score": Decimal(str(r["max"])), "learners_tested": r["learners"]}
        for r in rec["learning"]
    ]  # fmt: skip
    statements = [
        mock.patch.object(scoping, "resolve_user_scope", lambda principal: None),
        mock.patch.object(scoping, "cluster_queryset", lambda scope, base=None: chain(clusters)),
        mock.patch.object(oversight_service, "_staff_directory", lambda ids: directory),
        mock.patch.object(insights, "member_schools", lambda ids: members),
        # The loan records are the loans section's; the Command Center reads
        # only the count of schools holding one (MfiLoan below).
        mock.patch.object(
            outcomes, "loans_by_cluster",
            lambda ids, principal, members=None: {cid: outcomes.LoanSummary() for cid in ids},
        ),
        mock.patch.object(insights, "_delivered_sessions", lambda ids: sessions),
        mock.patch.object(ClusterActivityAttendance, "objects", chain(register)),
        mock.patch.object(impact_engine, "_latest_confirmed_records", lambda ids, year: latest[str(year)]),
        mock.patch.object(change_rules, "_published_rows", lambda **kw: chain(rule_rows)),
        mock.patch.object(SsaScore, "objects", scores),
        mock.patch.object(School, "objects", chain([])),
        mock.patch.object(
            SchoolEnrollmentHistory, "objects",
            chain([(r["school_id"], r["fy"], r["enrollment"]) for r in rec["enrolment"]]),
        ),
        mock.patch.object(LearningAssessmentResult, "objects", chain(learning)),
        mock.patch.object(MfiLoan, "objects", chain(list(rec["funded"]))),
        mock.patch.object(MostSignificantChangeStory, "objects", chain(stories)),
        mock.patch.object(User, "objects", chain([])),
        mock.patch.object(Activity, "objects", chain(plan)),
        mock.patch.object(ClusterScoreSetting, "objects", chain([setting] if setting else [])),
        mock.patch.object(
            SsaRecord, "objects",
            chain([{"id": r["id"], "school_id": r["school_id"], "average_score": r["average"]}
                   for r in rec["year_records"]]),
        ),
    ]  # fmt: skip
    for patch in statements:
        patch.start()
    try:
        ws = workspace.load(user, fy=fy, today=TODAY)
        scored = year_comparison.school_current_scores(
            [m["id"] for m in rec["members"]], fy
        )
    finally:
        for patch in reversed(statements):
            patch.stop()
    last = {key: day(value) for key, value in rec["last_delivered"].items()}
    with (
        mock.patch.object(workspace, "load", lambda principal, fy: ws),
        mock.patch.object(
            year_comparison, "school_current_scores", lambda ids, year: scored
        ),
        mock.patch.object(oversight_service, "_last_delivered_dates", lambda ids: last),
    ):
        status, body = read_page(
            user, "/cluster-oversight/", dict(sorted(query.items()))
        )
    if status != 200:
        raise RuntimeError(f"the page answered {status}: {body}")
    return body


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

    def case(name, rec, user, query=None, fy="2027"):
        query = query or {}
        cases.append(
            {
                "name": name,
                "role": user.active_role,
                "reader_ids": [i for i in (user.id, user.staff_profile_id) if i],
                "fy": fy,
                "years": sorted(fy_options(), reverse=True),
                "today": iso(TODAY),
                "query": query,
                "records": rec,
                "body": answer(rec, user, fy, query),
            }
        )

    officer = reader("cceo@edify.org")
    rich = make(11, clusters=12)
    case("an officer reads every figure", rich, officer)
    case("an Admin's loans count opens nothing", rich, reader("admin@edify.org"))
    case("a Regional Vice President is given no links and no Clusters door", rich,
         reader("cceo1@edify.org", "RegionalVicePresident"))  # fmt: skip
    case("an Accountant", make(12, clusters=9), reader("cceo1@edify.org", "Accountant"))
    case(
        "the fallback where no rule is published",
        make(13, clusters=10, rules=False),
        officer,
    )
    for seed in (21, 22, 23, 24):
        case(f"more clusters ({seed})", make(seed, clusters=14), reader("cd@edify.org"))
    stored = {
        "health": {"meetings": 0, "trainings": "35.5", "attendance": -4, "unknown": 9, "planning": None},
        "impact": {"ssa": 50, "loans": 0, "bt": True, "exams": "many", "teacher": 1e3},
        "teacher": {"training_attendance": 0, "teaching_ssa": 0, "learning_env_ssa": 0},
        "leader": {},
        "maturity": {"min_dimensions": 1.9, "active_sessions": "1", "active_participation": 10,
                     "healthy_health": 20, "healthy_ssa_improved": 5, "high_impact": 30,
                     "model_health": 25, "model_impact": 35, "model_stories": 0, "other": 3},
    }  # fmt: skip
    case(
        "stored weights and maturity rules",
        make(11, clusters=12, setting=stored),
        officer,
    )
    mine = [officer.id, officer.staff_profile_id]
    case(
        "My Clusters for someone who holds some of them",
        make(31, clusters=6, mine=mine),
        officer,
    )
    case(
        "no My Clusters for someone who holds them all",
        make(32, clusters=2, mine=mine),
        officer,
    )
    many = make(41, clusters=120)
    case(
        "a second page keeps the query",
        many,
        officer,
        {"rows_page": "2", "fy": "2027", "area": "a b&c"},
    )
    case("the first of three pages", many, officer)
    case(
        "a page past the last is the last",
        many,
        officer,
        {"rows_page": "99", "download": "1"},
    )
    case("eight pages make a gap", make(42, clusters=380), officer, {"rows_page": "4"})
    case("nothing in scope", make(51, clusters=0), officer)
    text = json.dumps(cases, ensure_ascii=False, separators=(",", ":"))
    with (
        OUT.open("wb") as raw,
        gzip.GzipFile(fileobj=raw, mode="wb", mtime=0) as packed,
    ):
        packed.write(text.encode("utf-8"))
    print(f"Wrote {OUT}: {len(cases)} cases")


main()
