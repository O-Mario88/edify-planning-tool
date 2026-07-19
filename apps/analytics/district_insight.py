"""Per-district snapshot for the sub-region map hover card.

Every metric is aggregated in the database and grouped by district, then the
groups are merged in pandas. The alternative -- looping 135 districts and
running a dozen queries each -- would be about 1,600 round trips on a page
that already does real work.

Definitions are borrowed rather than invented, so the card agrees with the KPI
cards above it on the same page:

* visits    = VISIT_TYPES from pl_analytics_service
* trainings = TRAINING_TYPES from pl_analytics_service
* delivered = COMPLETED_STATUSES from pl_analytics_service

That last one is a deliberate departure from the KPI cards above this map,
which count only ACHIEVED_STATUSES (ia_verified / closed /
accountant_confirmed). Coverage here answers "has this school been visited?",
and a visit that happened but has not yet cleared IA verification still
happened -- the school was still visited. Verification is a finance and
assurance lens, not a field-activity one.

The gap is not hypothetical: in the development database 260 of 277 activities
sit at `completed` and none have reached `ia_verified`, so the achieved lens
reports zero visits against 140 schools that were actually visited. Both
numbers are correct for what they measure; the card labels which one it is
shown, so the difference from the KPI strip is visible rather than confusing.

Two joins here are easy to get wrong and silently return zero:

* CoreSchoolProfile.school_id holds School.school_id (the business key such as
  "S-1464"), NOT School.id. Joining on School.id matches nothing at all. Only
  103 of the 325 profiles in the development database resolve to a live
  school; joining from the School side means the orphans simply do not count
  rather than inflating the total.
* School.cluster_id is a plain CharField holding Cluster.id, not a ForeignKey.

An absent measure stays absent. A district with no confirmed SSA reports
``ssa_avg = None``, never 0.0 -- a zero would read as "scored zero" and be
indistinguishable from a genuine floor score.
"""

from __future__ import annotations

from typing import Any

import pandas as pd
from django.db.models import Avg, Count, Q, Sum

from apps.analytics.pl_analytics_service import (
    COMPLETED_STATUSES,
    TRAINING_TYPES,
    VISIT_TYPES,
)
from apps.core.enums import SsaIntervention

SSA_CONFIRMED = "confirmed"
# Below this many scored assessments, naming a best and worst intervention is
# noise dressed as insight, so the card says so instead.
MIN_SCORES_FOR_INTERVENTION_CALL = 3

INTERVENTION_LABELS = dict(SsaIntervention.choices)


def _active_core_school_ids() -> set[str]:
    """School.school_id values with an active core profile."""
    from apps.core_schools.models import CoreSchoolProfile

    return set(
        CoreSchoolProfile.objects.filter(status="Active").values_list(
            "school_id", flat=True
        )
    )


def _frame(rows, key: str, **rename) -> pd.DataFrame:
    frame = pd.DataFrame.from_records(list(rows))
    if frame.empty:
        return pd.DataFrame(columns=["district_id", *rename.values()])
    return frame.rename(columns={key: "district_id", **rename})


def district_insight(fy: str | None = None) -> dict[str, dict[str, Any]]:
    """One snapshot per district, keyed by district name."""
    from apps.activities.models import Activity
    from apps.clusters.models import Cluster
    from apps.geography.models import District
    from apps.schools.models import School
    from apps.ssa.models import SsaRecord, SsaScore

    districts = list(
        District.objects.filter(sub_region__isnull=False).values(
            "id", "name", "sub_region__name"
        )
    )
    if not districts:
        return {}
    base = pd.DataFrame.from_records(districts).rename(
        columns={"id": "district_id", "name": "district", "sub_region__name": "subregion"}
    )

    core_ids = _active_core_school_ids()

    # ── counts ───────────────────────────────────────────────────────────────
    schools = _frame(
        School.objects.values("district_id").annotate(n=Count("id")),
        "district_id", n="schools",
    )
    clusters = _frame(
        Cluster.objects.values("district_id").annotate(n=Count("id")),
        "district_id", n="clusters",
    )
    core = _frame(
        School.objects.filter(school_id__in=core_ids)
        .values("district_id")
        .annotate(n=Count("id")),
        "district_id", n="core_schools",
    )

    # ── SSA, confirmed only ──────────────────────────────────────────────────
    ssa_qs = SsaRecord.objects.filter(
        verification_status=SSA_CONFIRMED,
        school__district__sub_region__isnull=False,
        average_score__isnull=False,
    )
    if fy:
        ssa_qs = ssa_qs.filter(fy=fy)

    ssa = _frame(
        ssa_qs.values("school__district_id").annotate(
            avg=Avg("average_score"),
            n=Count("id"),
            assessed=Count("school", distinct=True),
        ),
        "school__district_id", avg="ssa_avg", n="ssa_n", assessed="ssa_schools",
    )
    ssa_cluster = _frame(
        ssa_qs.exclude(school__cluster_id__isnull=True)
        .exclude(school__cluster_id="")
        .values("school__district_id")
        .annotate(avg=Avg("average_score")),
        "school__district_id", avg="ssa_avg_cluster",
    )
    ssa_core = _frame(
        ssa_qs.filter(school__school_id__in=core_ids)
        .values("school__district_id")
        .annotate(avg=Avg("average_score")),
        "school__district_id", avg="ssa_avg_core",
    )

    # ── activity coverage ────────────────────────────────────────────────────
    acts = Activity.objects.filter(
        status__in=COMPLETED_STATUSES, school__district__sub_region__isnull=False
    )
    if fy:
        acts = acts.filter(fy=fy)

    trained = _frame(
        acts.filter(activity_type__in=TRAINING_TYPES)
        .values("school__district_id")
        .annotate(n=Count("school", distinct=True)),
        "school__district_id", n="schools_trained",
    )
    visited = _frame(
        acts.filter(activity_type__in=VISIT_TYPES)
        .values("school__district_id")
        .annotate(n=Count("school", distinct=True)),
        "school__district_id", n="schools_visited",
    )
    people = _frame(
        acts.values("school__district_id").annotate(
            t=Sum("teachers_attended"), l=Sum("leaders_attended")
        ),
        "school__district_id", t="teachers_trained", l="leaders_trained",
    )

    for part in (schools, clusters, core, ssa, ssa_cluster, ssa_core,
                 trained, visited, people):
        if not part.empty:
            base = base.merge(part, on="district_id", how="left")

    counts = ["schools", "clusters", "core_schools", "ssa_n", "ssa_schools",
              "schools_trained", "schools_visited", "teachers_trained",
              "leaders_trained"]
    for col in counts:
        if col not in base:
            base[col] = 0
        base[col] = base[col].fillna(0).astype(int)
    for col in ("ssa_avg", "ssa_avg_cluster", "ssa_avg_core"):
        if col not in base:
            base[col] = pd.NA

    # ── best / worst intervention, per district ──────────────────────────────
    scores = SsaScore.objects.filter(
        ssa_record__verification_status=SSA_CONFIRMED,
        ssa_record__school__district__sub_region__isnull=False,
    )
    if fy:
        scores = scores.filter(ssa_record__fy=fy)
    iv = pd.DataFrame.from_records(
        list(
            scores.values(
                "ssa_record__school__district_id", "intervention"
            ).annotate(avg=Avg("score"), n=Count("id"))
        )
    )
    best_worst: dict[str, tuple] = {}
    if not iv.empty:
        iv = iv.rename(columns={"ssa_record__school__district_id": "district_id"})
        for did, group in iv.groupby("district_id"):
            # Judge on the district's total scored assessments, not on any one
            # intervention: a district with two records would otherwise get a
            # confident "strongest" and "weakest" from a single pair.
            if int(group["n"].sum()) < MIN_SCORES_FOR_INTERVENTION_CALL:
                continue
            top = group.loc[group["avg"].idxmax()]
            bottom = group.loc[group["avg"].idxmin()]
            if top["intervention"] == bottom["intervention"]:
                continue  # only one intervention scored; nothing to contrast
            best_worst[did] = (
                (INTERVENTION_LABELS.get(top["intervention"], top["intervention"]),
                 round(float(top["avg"]), 2)),
                (INTERVENTION_LABELS.get(bottom["intervention"], bottom["intervention"]),
                 round(float(bottom["avg"]), 2)),
            )

    # ── assemble ─────────────────────────────────────────────────────────────
    def num(v):
        return None if pd.isna(v) else round(float(v), 2)

    out: dict[str, dict[str, Any]] = {}
    for _i, r in base.iterrows():
        bw = best_worst.get(r["district_id"])
        out[r["district"]] = {
            "district": r["district"],
            "subregion": r["subregion"],
            "schools": int(r["schools"]),
            "clusters": int(r["clusters"]),
            "core_schools": int(r["core_schools"]),
            "ssa_done": int(r["ssa_schools"]),
            "ssa_total": int(r["schools"]),
            "ssa_avg": num(r["ssa_avg"]),
            "ssa_avg_cluster": num(r["ssa_avg_cluster"]),
            "ssa_avg_core": num(r["ssa_avg_core"]),
            "best": {"name": bw[0][0], "score": bw[0][1]} if bw else None,
            "worst": {"name": bw[1][0], "score": bw[1][1]} if bw else None,
            "trained": int(r["schools_trained"]),
            "visited": int(r["schools_visited"]),
            "teachers_trained": int(r["teachers_trained"]),
            "leaders_trained": int(r["leaders_trained"]),
        }
    return out
