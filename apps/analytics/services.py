"""
Analytics service — role-scoped summaries + SSA performance + impact +
correlation + contribution. Aggregates over the schools/SSA/activities models,
scope-constrained. Ports the legacy analytics.service aggregation logic.
"""
from __future__ import annotations

from django.db.models import Avg, Count, Q, Sum

from apps.core.fy import get_operational_fy
from apps.core.scoping import resolve_user_scope, school_queryset, aggregate_school_filter
from apps.schools.models import School


def _scoped_schools(principal):
    scope = resolve_user_scope(principal)
    qs = School.objects.filter(deleted_at__isnull=True)
    if scope.country_scope or scope.can_view_summary_only:
        return qs, scope
    if scope.school_ids:
        return qs.filter(id__in=scope.school_ids), scope
    return qs.none(), scope


def dashboard_summary(principal, query: dict) -> dict:
    """One conditional-aggregation query instead of 9 separate COUNTs — a single
    pass over the scoped school set returns every breakdown the dashboard strip
    needs. With 1,000 schools this turns 9 scans into 1."""
    schools, scope = _scoped_schools(principal)
    fy = query.get("fy") or get_operational_fy()
    agg = schools.aggregate(
        total=Count("id"),
        core=Count("id", filter=Q(school_type="core")),
        champion=Count("id", filter=Q(school_type="champion")),
        client=Count("id", filter=Q(school_type="client")),
        ssa_done=Count("id", filter=Q(current_fy_ssa_status="done")),
        clustered=Count("id", filter=Q(cluster_status="clustered")),
        planning_ready=Count("id", filter=Q(planning_readiness="ready")),
    )
    return {
        "role": scope.active_role or "",
        "scope": {
            "countryScope": scope.country_scope,
            "schoolsInScope": agg["total"],
        },
        "schools": agg["total"],
        "coreSchools": agg["core"],
        "clientSchools": agg["client"],
        "planningReady": agg["planning_ready"],
        "unclustered": (agg["total"] or 0) - (agg["clustered"] or 0),
        "ssaDone": agg["ssa_done"],
        "fy": fy,
    }


def leadership_summary(principal, query: dict) -> dict:
    from apps.activities.models import Activity
    from apps.ssa.models import SsaRecord, SsaScore
    
    schools, scope = _scoped_schools(principal)
    fy = query.get("fy") or get_operational_fy()
    total_schools = schools.count()
    
    if total_schools == 0:
        return {
            "countryScope": scope.country_scope,
            "schools": 0, "coreSchools": 0, "clientSchools": 0,
            "clustered": 0, "unclustered": 0, "ssaDone": 0, "ssaPending": 0,
            "ssaCompletePct": 0.0, "ssaAverage": 0.0,
            "byIntervention": [], "weakestInterventions": [],
            "pipeline": { "planned": 0, "scheduled": 0, "inProgress": 0, "evidenceUploaded": 0, "awaitingIa": 0, "iaVerified": 0, "completed": 0 },
            "activitiesTotal": 0,
            "staffCount": 0, "partnerCount": 0,
            "fundRequests": 0, "paymentsCleared": 0, "disbursedTotalUgx": 0,
        }
        
    core = schools.filter(school_type="core").count()
    client = schools.filter(school_type="client").count()
    clustered = schools.filter(cluster_status="clustered").count()
    unclustered = max(0, total_schools - clustered)
    ssa_done = schools.filter(current_fy_ssa_status="done").count()
    ssa_pending = schools.filter(current_fy_ssa_status="pending").count()
    
    coverage = round((ssa_done / total_schools * 100), 1) if total_schools else 0.0
    
    ssa_avg_val = SsaRecord.objects.filter(school__in=schools, fy=fy, deleted_at__isnull=True).aggregate(a=Avg("average_score"))["a"]
    ssa_average = round(ssa_avg_val, 1) if ssa_avg_val is not None else 0.0
    
    scores = SsaScore.objects.filter(ssa_record__school__in=schools, ssa_record__fy=fy, ssa_record__deleted_at__isnull=True)
    interventions_grouped = (
        scores.values("intervention")
        .annotate(avg=Avg("score"))
        .order_by("avg")
    )
    by_intervention = [
        {"intervention": item["intervention"], "average": round(item["avg"], 1) if item["avg"] is not None else 0.0}
        for item in interventions_grouped
    ]
    
    acts = Activity.objects.filter(deleted_at__isnull=True, fy=fy)
    if not scope.country_scope:
        if scope.staff_ids:
            acts = acts.filter(responsible_staff_id__in=scope.staff_ids)
        elif scope.partner_ids:
            acts = acts.filter(assigned_partner_id__in=scope.partner_ids)
        else:
            acts = acts.none()
            
    planned = acts.filter(status="planned").count()
    scheduled = acts.filter(status="scheduled").count()
    in_progress = acts.filter(status="in_progress").count()
    evidence_uploaded = acts.filter(status="evidence_uploaded").count()
    awaiting_ia = acts.filter(status="awaiting_ia_verification").count()
    ia_verified = acts.filter(status="ia_verified").count()
    completed = acts.filter(status__in=["completed", "ia_verified", "accountant_confirmed"]).count()
    
    pipeline = {
        "planned": planned,
        "scheduled": scheduled,
        "inProgress": in_progress,
        "evidenceUploaded": evidence_uploaded,
        "awaitingIa": awaiting_ia,
        "iaVerified": ia_verified,
        "completed": completed,
    }
    
    staff_count = acts.exclude(responsible_staff_id__isnull=True).values("responsible_staff_id").distinct().count()
    partner_count = acts.exclude(assigned_partner_id__isnull=True).values("assigned_partner_id").distinct().count()
    
    disbursed_cents = acts.filter(status__in=["completed", "ia_verified", "accountant_confirmed"]).aggregate(s=Sum("est_cost_cents"))["s"] or 0
    disbursed_total_ugx = disbursed_cents // 100
    
    return {
        "countryScope": scope.country_scope,
        "schools": total_schools,
        "coreSchools": core,
        "clientSchools": client,
        "clustered": clustered,
        "unclustered": unclustered,
        "ssaDone": ssa_done,
        "ssaPending": ssa_pending,
        "ssaCompletePct": coverage,
        "ssaAverage": ssa_average,
        "byIntervention": by_intervention,
        "weakestInterventions": by_intervention[:3],
        "pipeline": pipeline,
        "activitiesTotal": acts.count(),
        "staffCount": staff_count,
        "partnerCount": partner_count,
        "fundRequests": 0,
        "paymentsCleared": completed,
        "disbursedTotalUgx": disbursed_total_ugx,
    }


def district_rollups(principal, query: dict) -> dict:
    schools, scope = _scoped_schools(principal)
    rows = (
        schools.filter(district_id__isnull=False)
        .values("district_id", "district__name")
        .annotate(
            total=Count("id"),
            ssa_done=Count("id", filter=Q(current_fy_ssa_status="done")),
            core=Count("id", filter=Q(school_type__in=["core", "champion"])),
        )
        .order_by("district__name")
    )
    districts = [
        {
            "districtId": r["district_id"],
            "district": r["district__name"],
            "total": r["total"],
            "ssaDone": r["ssa_done"],
            "coverage": round((r["ssa_done"] / r["total"] * 100), 1) if r["total"] else 0,
            "core": r["core"],
        }
        for r in rows
    ]
    return {"districts": districts}


def coverage_summary(principal, query: dict) -> dict:
    schools, scope = _scoped_schools(principal)
    total = schools.count()
    ssa_done = schools.filter(current_fy_ssa_status="done").count()
    clustered = schools.filter(cluster_status="clustered").count()
    return {
        "ssaCoverage": round((ssa_done / total * 100), 1) if total else 0,
        "clusterCoverage": round((clustered / total * 100), 1) if total else 0,
        "schoolsTotal": total,
    }


def geo_map_districts(principal, query: dict) -> list[dict]:
    return district_rollups(principal, query)


def geo_map_district_detail(principal, district_id: str) -> dict:
    schools, scope = _scoped_schools(principal)
    qs = schools.filter(district_id=district_id)
    return {
        "districtId": district_id,
        "schoolCount": qs.count(),
        "schools": [
            {"id": s.id, "schoolId": s.school_id, "name": s.name,
             "schoolType": s.school_type, "latitude": s.latitude, "longitude": s.longitude}
            for s in qs[:500]
        ],
    }


def school_directory_summary(principal, query: dict) -> dict:
    return dashboard_summary(principal, query)


def ssa_performance(principal, query: dict) -> dict:
    from apps.ssa.models import SsaRecord

    schools, scope = _scoped_schools(principal)
    fy = query.get("fy") or get_operational_fy()
    school_ids = list(schools.values_list("id", flat=True))
    records = SsaRecord.objects.filter(school_id__in=school_ids, fy=fy, deleted_at__isnull=True)
    avg = records.aggregate(a=Avg("average_score"))["a"]
    return {
        "fy": fy,
        "recordsCount": records.count(),
        "averageScore": round(avg, 2) if avg else None,
    }


def ssa_performance_grouped(principal, query: dict) -> dict:
    from apps.ssa.models import SsaRecord, SsaScore
    from apps.core.enums import SsaIntervention

    schools, scope = _scoped_schools(principal)
    fy = query.get("fy") or get_operational_fy()
    group_by = query.get("groupBy", "district")
    school_type = query.get("schoolType") or "all"
    
    if school_type == "core":
        schools = schools.filter(school_type__in=["core", "champion"])
    elif school_type == "client":
        schools = schools.filter(school_type="client")

    if group_by == "region":
        group_field = "region_id"
        name_field = "region__name"
    elif group_by == "subCounty":
        group_field = "sub_county_id"
        name_field = "sub_county__name"
    elif group_by == "cluster":
        group_field = "cluster_id"
        name_field = "cluster_id"
    else:
        group_field = "district_id"
        name_field = "district__name"

    school_groups = (
        schools.filter(**{f"{group_field}__isnull": False})
        .values(group_field, name_field)
        .annotate(total=Count("id"))
    )

    if not school_groups:
        return {
            "fy": fy,
            "groupBy": group_by,
            "schoolType": school_type,
            "canGroupByCceo": principal.active_role in ("Admin", "CountryDirector", "CountryProgramLead", "IA"),
            "interventions": [{"code": i.value, "label": i.label} for i in SsaIntervention],
            "rows": []
        }

    group_map = {}
    for sg in school_groups:
        gid = sg[group_field]
        gname = sg[name_field]
        if group_by == "cluster":
            from apps.clusters.models import Cluster
            cluster_obj = Cluster.objects.filter(id=gid).first()
            gname = cluster_obj.name if cluster_obj else f"Cluster {gid}"

        group_map[gid] = {
            "groupId": gid,
            "groupName": gname or "Unknown",
            "schoolCount": sg["total"],
            "schoolsAssessed": 0,
            "overallAverage": None,
            "interventions": {i.value: None for i in SsaIntervention},
            "records": []
        }

    records = SsaRecord.objects.filter(
        school__in=schools,
        fy=fy,
        deleted_at__isnull=True
    ).values("id", f"school__{group_field}", "average_score")

    record_ids = []
    for r in records:
        gid = r[f"school__{group_field}"]
        if gid in group_map:
            group_map[gid]["records"].append(r)
            record_ids.append(r["id"])

    assessed_counts = (
        SsaRecord.objects.filter(school__in=schools, fy=fy, deleted_at__isnull=True)
        .values(f"school__{group_field}")
        .annotate(unique_schools=Count("school_id", distinct=True))
    )
    for ac in assessed_counts:
        gid = ac[f"school__{group_field}"]
        if gid in group_map:
            group_map[gid]["schoolsAssessed"] = ac["unique_schools"]

    scores = (
        SsaScore.objects.filter(ssa_record_id__in=record_ids)
        .values("ssa_record__school__{}".format(group_field), "intervention")
        .annotate(avg_score=Avg("score"))
    )

    for s in scores:
        gid = s["ssa_record__school__{}".format(group_field)]
        intervention = s["intervention"]
        avg_score = s["avg_score"]
        if gid in group_map:
            group_map[gid]["interventions"][intervention] = round(avg_score, 1) if avg_score is not None else None

    for gid, gdata in group_map.items():
        recs = gdata["records"]
        if recs:
            avg_sum = sum(r["average_score"] for r in recs if r["average_score"] is not None)
            count = sum(1 for r in recs if r["average_score"] is not None)
            gdata["overallAverage"] = round(avg_sum / count, 1) if count > 0 else None

    rows_data = []
    for gid, gdata in group_map.items():
        school_count = gdata["schoolCount"]
        schools_assessed = gdata["schoolsAssessed"]
        rows_data.append({
            "groupId": gdata["groupId"],
            "groupName": gdata["groupName"],
            "schoolCount": school_count,
            "schoolsAssessed": schools_assessed,
            "schoolsMissingSSA": max(0, school_count - schools_assessed),
            "interventions": gdata["interventions"],
            "overallAverage": gdata["overallAverage"]
        })

    rows_data.sort(key=lambda r: r["groupName"])

    return {
        "fy": fy,
        "groupBy": group_by,
        "schoolType": school_type,
        "canGroupByCceo": principal.active_role in ("Admin", "CountryDirector", "CountryProgramLead", "IA"),
        "interventions": [{"code": i.value, "label": i.label} for i in SsaIntervention],
        "rows": rows_data
    }


def intervention_improvement(principal, query: dict) -> dict:
    from django.db.models import Avg, Count, Q
    from apps.core.enums import SsaIntervention
    from apps.ssa.models import SsaRecord, SsaScore

    schools, scope = _scoped_schools(principal)
    
    current_fy = query.get("currentFy") or get_operational_fy()
    prev_fy = str(int(current_fy) - 1)
    
    group_by = query.get("groupBy", "district")
    school_type = query.get("schoolType") or "core"
    
    if school_type == "core":
        schools = schools.filter(school_type__in=["core", "champion"])
    elif school_type == "client":
        schools = schools.filter(school_type="client")

    if group_by == "region":
        group_field = "region_id"
        name_field = "region__name"
    elif group_by == "subCounty":
        group_field = "sub_county_id"
        name_field = "sub_county__name"
    elif group_by == "cluster":
        group_field = "cluster_id"
        name_field = "cluster_id"
    else:
        group_field = "district_id"
        name_field = "district__name"

    school_groups = (
        schools.filter(**{f"{group_field}__isnull": False})
        .values(group_field, name_field)
        .annotate(total=Count("id"))
    )

    if not school_groups:
        return {
            "currentFy": current_fy,
            "prevFy": prev_fy,
            "groupBy": group_by,
            "schoolType": school_type,
            "canGroupByCceo": principal.active_role in ("Admin", "CountryDirector", "CountryProgramLead", "IA"),
            "interventions": [{"code": i.value, "label": i.label} for i in SsaIntervention],
            "rows": []
        }

    group_map = {}
    for sg in school_groups:
        gid = sg[group_field]
        gname = sg[name_field]
        if group_by == "cluster":
            from apps.clusters.models import Cluster
            cluster_obj = Cluster.objects.filter(id=gid).first()
            gname = cluster_obj.name if cluster_obj else f"Cluster {gid}"

        group_map[gid] = {
            "groupId": gid,
            "groupName": gname or "Unknown",
            "schools": [],
            "schoolsImproved": 0,
            "schoolsDeclined": 0,
            "schoolsNoChange": 0,
            "schoolsNoComparison": 0,
        }

    school_list = list(schools.values("id", group_field))
    for s in school_list:
        gid = s[group_field]
        if gid in group_map:
            group_map[gid]["schools"].append(s["id"])

    records_curr = {
        r["school_id"]: r
        for r in SsaRecord.objects.filter(school__in=schools, fy=current_fy, deleted_at__isnull=True).values("id", "school_id", "average_score")
    }
    records_prev = {
        r["school_id"]: r
        for r in SsaRecord.objects.filter(school__in=schools, fy=prev_fy, deleted_at__isnull=True).values("id", "school_id", "average_score")
    }

    curr_record_ids = []
    prev_record_ids = []
    
    for s in school_list:
        sid = s["id"]
        gid = s[group_field]
        if gid not in group_map:
            continue
            
        r_curr = records_curr.get(sid)
        r_prev = records_prev.get(sid)
        
        if r_curr and r_prev:
            curr_record_ids.append(r_curr["id"])
            prev_record_ids.append(r_prev["id"])
            
            diff = (r_curr["average_score"] or 0) - (r_prev["average_score"] or 0)
            if diff > 0.05:
                group_map[gid]["schoolsImproved"] += 1
            elif diff < -0.05:
                group_map[gid]["schoolsDeclined"] += 1
            else:
                group_map[gid]["schoolsNoChange"] += 1
        else:
            group_map[gid]["schoolsNoComparison"] += 1

    scores_curr = (
        SsaScore.objects.filter(ssa_record_id__in=curr_record_ids)
        .values("ssa_record__school__{}".format(group_field), "intervention")
        .annotate(avg=Avg("score"))
    )
    scores_prev = (
        SsaScore.objects.filter(ssa_record_id__in=prev_record_ids)
        .values("ssa_record__school__{}".format(group_field), "intervention")
        .annotate(avg=Avg("score"))
    )

    curr_avgs = {}
    prev_avgs = {}
    
    for s in scores_curr:
        gid = s["ssa_record__school__{}".format(group_field)]
        if gid not in curr_avgs:
            curr_avgs[gid] = {}
        curr_avgs[gid][s["intervention"]] = s["avg"]
        
    for s in scores_prev:
        gid = s["ssa_record__school__{}".format(group_field)]
        if gid not in prev_avgs:
            prev_avgs[gid] = {}
        prev_avgs[gid][s["intervention"]] = s["avg"]

    rows = []
    for gid, gdata in group_map.items():
        total_compared = gdata["schoolsImproved"] + gdata["schoolsDeclined"] + gdata["schoolsNoChange"]
        improvement_rate = round(gdata["schoolsImproved"] / total_compared * 100) if total_compared > 0 else None
        
        interventions_data = []
        best_intervention = None
        declining_intervention = None
        weakest_intervention = None
        
        for i in SsaIntervention:
            curr_val = curr_avgs.get(gid, {}).get(i.value)
            prev_val = prev_avgs.get(gid, {}).get(i.value)
            
            curr_avg = round(curr_val, 2) if curr_val is not None else None
            prev_avg = round(prev_val, 2) if prev_val is not None else None
            change = round(curr_val - prev_val, 2) if (curr_val is not None and prev_val is not None) else None
            
            interventions_data.append({
                "code": i.value,
                "label": i.label,
                "prevAvg": prev_avg,
                "currAvg": curr_avg,
                "change": change
            })
            
            if change is not None:
                if change > 0:
                    if best_intervention is None or change > best_intervention["change"]:
                        best_intervention = {"code": i.value, "label": i.label, "change": change}
                elif change < 0:
                    if declining_intervention is None or change < declining_intervention["change"]:
                        declining_intervention = {"code": i.value, "label": i.label, "change": change}
                        
            if curr_avg is not None:
                if weakest_intervention is None or curr_avg < weakest_intervention["currAvg"]:
                    weakest_intervention = {"code": i.value, "label": i.label, "currAvg": curr_avg}

        rows.append({
            "groupId": gid,
            "groupName": gdata["groupName"],
            "schoolsImproved": gdata["schoolsImproved"],
            "schoolsDeclined": gdata["schoolsDeclined"],
            "schoolsNoChange": gdata["schoolsNoChange"],
            "schoolsNoComparison": gdata["schoolsNoComparison"],
            "improvementRate": improvement_rate,
            "bestIntervention": best_intervention,
            "decliningIntervention": declining_intervention,
            "weakestIntervention": weakest_intervention,
            "interventions": interventions_data
        })

    rows.sort(key=lambda r: r["groupName"])

    return {
        "currentFy": current_fy,
        "prevFy": prev_fy,
        "groupBy": group_by,
        "schoolType": school_type,
        "canGroupByCceo": principal.active_role in ("Admin", "CountryDirector", "CountryProgramLead", "IA"),
        "interventions": [{"code": i.value, "label": i.label} for i in SsaIntervention],
        "rows": rows
    }


def support_ssa_correlation(principal, query: dict) -> dict:
    """Layer-3 correlation: does support timing improve SSA?"""
    from apps.activities.models import Activity
    from apps.ssa.models import SsaRecord

    schools, scope = _scoped_schools(principal)
    fy = query.get("fy") or get_operational_fy()
    # For each school with both support + SSA this FY, compare SSA avg.
    school_ids = list(schools.values_list("id", flat=True))
    with_support = SsaRecord.objects.filter(
        school_id__in=school_ids, fy=fy, deleted_at__isnull=True,
        school__activities__deleted_at__isnull=True,
        school__activities__fy=fy,
    ).distinct().aggregate(a=Avg("average_score"))["a"]
    without_support = SsaRecord.objects.filter(
        school_id__in=school_ids, fy=fy, deleted_at__isnull=True,
    ).exclude(school__activities__fy=fy).aggregate(a=Avg("average_score"))["a"]
    return {
        "fy": fy,
        "withSupportAvg": round(with_support, 2) if with_support else None,
        "withoutSupportAvg": round(without_support, 2) if without_support else None,
    }


def staff_vs_partner_correlation(principal, query: dict) -> dict:
    from apps.ssa.models import SsaRecord

    schools, scope = _scoped_schools(principal)
    fy = query.get("fy") or get_operational_fy()
    staff = SsaRecord.objects.filter(
        school__in=schools, fy=fy, collector_type="staff", deleted_at__isnull=True
    ).aggregate(a=Avg("average_score"))["a"]
    partner = SsaRecord.objects.filter(
        school__in=schools, fy=fy, collector_type="partner", deleted_at__isnull=True
    ).aggregate(a=Avg("average_score"))["a"]
    return {
        "staffAvg": round(staff, 2) if staff else None,
        "partnerAvg": round(partner, 2) if partner else None,
    }


def activity_pipeline(principal, query: dict) -> dict:
    from apps.activities.models import Activity

    scope = resolve_user_scope(principal)
    fy = query.get("fy") or get_operational_fy()
    qs = Activity.objects.filter(deleted_at__isnull=True, fy=fy)
    if not scope.country_scope:
        if scope.staff_ids:
            qs = qs.filter(responsible_staff_id__in=scope.staff_ids)
        elif scope.partner_ids:
            qs = qs.filter(assigned_partner_id__in=scope.partner_ids)
        else:
            qs = qs.none()

    statuses = ("not_planned", "planned", "scheduled", "completed", "awaiting_ia_verification", "ia_verified")
    by_status = [
        {"status": s, "count": qs.filter(status=s).count()}
        for s in statuses
    ]

    deliveries = ("staff", "partner")
    by_delivery = [
        {"deliveryType": d, "count": qs.filter(delivery_type=d).count()}
        for d in deliveries
    ]

    return {
        "fy": fy,
        "total": qs.count(),
        "byStatus": by_status,
        "byDelivery": by_delivery,
        "completed": qs.filter(status__in=["completed", "ia_verified"]).count(),
    }


def contribution_summary(principal, query: dict) -> dict:
    from django.db.models import Sum, Q, Count
    from apps.activities.models import Activity
    from apps.schools.models import School
    from apps.ssa.models import SsaRecord

    schools, scope = _scoped_schools(principal)
    fy = query.get("fy") or get_operational_fy()
    prev_fy = str(int(fy) - 1)
    lens = query.get("lens", "own")

    if lens == "team" and scope.supervised_staff_ids:
        schools_in_lens = School.objects.filter(deleted_at__isnull=True, account_owner_id__in=scope.supervised_staff_ids)
    elif lens == "combined" and scope.supervised_staff_ids:
        schools_in_lens = School.objects.filter(deleted_at__isnull=True, account_owner_id__in=list(scope.supervised_staff_ids) + list(scope.staff_ids or []))
    else:
        schools_in_lens = schools

    completed_qs = Activity.objects.filter(deleted_at__isnull=True, fy=fy, status__in=["completed", "ia_verified", "accountant_confirmed"])
    if lens == "team" and scope.supervised_staff_ids:
        completed_qs = completed_qs.filter(responsible_staff_id__in=scope.supervised_staff_ids)
    elif lens == "combined" and scope.supervised_staff_ids:
        completed_qs = completed_qs.filter(responsible_staff_id__in=list(scope.supervised_staff_ids) + list(scope.staff_ids or []))
    elif scope.staff_ids:
        completed_qs = completed_qs.filter(responsible_staff_id__in=scope.staff_ids)
    else:
        completed_qs = completed_qs.none()

    # Headline statistics should only count verified activities (ia_verified or accountant_confirmed)
    verified_completed_qs = completed_qs.filter(status__in=["ia_verified", "accountant_confirmed"])

    reached_school_ids = list(verified_completed_qs.filter(school_id__isnull=False).values_list("school_id", flat=True).distinct())
    reached_schools = School.objects.filter(id__in=reached_school_ids, deleted_at__isnull=True)
    
    schools_reached_count = reached_schools.count()
    client_schools_reached = reached_schools.filter(school_type="client").count()
    core_schools_supported = reached_schools.filter(school_type="core").count()
    project_schools_supported = reached_schools.filter(school_type="champion").count()
    
    learners_impacted = reached_schools.aggregate(total=Sum("enrollment"))["total"] or 0
    
    totals_trained = verified_completed_qs.aggregate(
        teachers=Sum("teachers_attended"),
        leaders=Sum("leaders_attended")
    )
    teachers_trained = totals_trained["teachers"] or 0
    leaders_trained = totals_trained["leaders"] or 0

    districts_covered = reached_schools.values("district_id").distinct().count()
    sub_counties_covered = reached_schools.values("sub_county_id").distinct().count()
    clusters_covered = reached_schools.values("cluster_id").exclude(Q(cluster_id__isnull=True) | Q(cluster_id="")).distinct().count()
    regions_covered = reached_schools.values("region_id").distinct().count()

    VISIT_TYPES = {"school_visit", "follow_up_visit", "coaching_visit", "core_visit"}
    TRAINING_TYPES = {"training", "school_improvement_training", "cluster_training", "core_training"}

    visits_completed = verified_completed_qs.filter(activity_type__in=VISIT_TYPES).count()
    trainings_completed = verified_completed_qs.filter(activity_type__in=TRAINING_TYPES).count()
    cluster_meetings_completed = verified_completed_qs.filter(activity_type="cluster_meeting").count()

    ssa_completed = SsaRecord.objects.filter(school__in=schools_in_lens, fy=fy, deleted_at__isnull=True).count()

    records_curr = {
        r["school_id"]: r
        for r in SsaRecord.objects.filter(school__in=schools_in_lens, fy=fy, deleted_at__isnull=True).values("id", "school_id", "average_score")
    }
    records_prev = {
        r["school_id"]: r
        for r in SsaRecord.objects.filter(school__in=schools_in_lens, fy=prev_fy, deleted_at__isnull=True).values("id", "school_id", "average_score")
    }
    
    schools_improved = 0
    for sid in records_curr:
        r_curr = records_curr[sid]
        r_prev = records_prev.get(sid)
        if r_curr and r_prev:
            diff = (r_curr["average_score"] or 0) - (r_prev["average_score"] or 0)
            if diff > 0.05:
                schools_improved += 1

    # Calculate best/worst interventions
    from apps.core.enums import SsaIntervention
    from apps.ssa.models import SsaScore
    curr_rec_ids = [r["id"] for r in records_curr.values()]
    prev_rec_ids = [r["id"] for r in records_prev.values()]
    
    curr_avgs = dict(SsaScore.objects.filter(ssa_record_id__in=curr_rec_ids).values("intervention").annotate(a=Avg("score")).values_list("intervention", "a"))
    prev_avgs = dict(SsaScore.objects.filter(ssa_record_id__in=prev_rec_ids).values("intervention").annotate(a=Avg("score")).values_list("intervention", "a"))
    
    best_intervention = None
    worst_intervention = None
    best_change = -999.0
    worst_change = 999.0
    
    for i in SsaIntervention:
        curr_val = curr_avgs.get(i.value)
        prev_val = prev_avgs.get(i.value)
        if curr_val is not None and prev_val is not None:
            change = float(curr_val) - float(prev_val)
            if change > best_change:
                best_change = change
                best_intervention = i.value
            if change < worst_change:
                worst_change = change
                worst_intervention = i.value

    # Staff vs partner activities are counted from all completed/delivered activities
    partner_activities = completed_qs.filter(delivery_type="partner").count()
    staff_activities = completed_qs.filter(delivery_type="staff").count()
    ia_verified_activities = completed_qs.filter(status__in=["ia_verified", "accountant_confirmed"]).count()

    # Evidence pending query
    pending_qs = Activity.objects.filter(deleted_at__isnull=True, fy=fy, status="evidence_uploaded")
    if lens == "team" and scope.supervised_staff_ids:
        pending_qs = pending_qs.filter(responsible_staff_id__in=scope.supervised_staff_ids)
    elif lens == "combined" and scope.supervised_staff_ids:
        pending_qs = pending_qs.filter(responsible_staff_id__in=list(scope.supervised_staff_ids) + list(scope.staff_ids or []))
    elif scope.staff_ids:
        pending_qs = pending_qs.filter(responsible_staff_id__in=scope.staff_ids)
    else:
        pending_qs = pending_qs.none()
        
    evidence_pending = pending_qs.count()
    salesforce_ids_pending = completed_qs.filter(Q(salesforce_activity_id__isnull=True) | Q(salesforce_activity_id="")).count()

    metrics = {
        "schoolsReached": schools_reached_count,
        "clientSchoolsReached": client_schools_reached,
        "coreSchoolsSupported": core_schools_supported,
        "projectSchoolsSupported": project_schools_supported,
        "learnersImpacted": learners_impacted,
        "teachersTrained": teachers_trained,
        "schoolLeadersTrained": leaders_trained,
        "districtsCovered": districts_covered,
        "subCountiesCovered": sub_counties_covered,
        "clustersCovered": clusters_covered,
        "regionsCovered": regions_covered,
        "visitsCompleted": visits_completed,
        "trainingsCompleted": trainings_completed,
        "clusterMeetingsCompleted": cluster_meetings_completed,
        "ssaCompleted": ssa_completed,
        "schoolsImproved": schools_improved,
        "partnerActivities": partner_activities,
        "staffActivities": staff_activities,
        "iaVerifiedActivities": ia_verified_activities,
        "evidencePending": evidence_pending,
        "salesforceIdsPending": salesforce_ids_pending,
        "bestIntervention": best_intervention,
        "worstIntervention": worst_intervention,
    }

    return {
        "fy": fy,
        "lens": lens,
        "canViewTeam": scope.can_view_team,
        "summaryOnly": False,
        "schoolsInScope": schools_in_lens.count(),
        "metrics": metrics,
        "dataQuality": []
    }


def recruitment_recommendation(principal, query: dict) -> dict:
    from django.db.models import Avg, Count, Sum, Q
    from apps.ssa.models import SsaRecord
    from apps.activities.models import Activity

    schools, scope = _scoped_schools(principal)
    fy = query.get("fy") or get_operational_fy()
    prev_fy = str(int(fy) - 1)
    
    total = schools.count()
    if total == 0:
        return {
            "fy": fy,
            "scope": "country" if scope.country_scope else "team",
            "readinessScore": 0,
            "recommendation": "Pause Recruitment and Support Current Schools",
            "reason": "No schools in scope.",
            "capacity": { "totalSchools": 0, "core": 0, "client": 0, "reachedPct": 0, "partnerPaymentBacklog": 0, "partnerEvidencePending": 0, "partnerStrainPct": 0 },
            "ssaReadiness": { "currentSsaPct": 0, "previousSsaPct": 0, "impactReadyPct": 0, "missingCurrentSsa": 0 },
            "dataQuality": { "missingCluster": 0, "unmatchedOwner": 0, "duplicates": 0, "missingEnrollment": 0, "penaltyPct": 0 },
            "impact": { "schoolsImproved": 0, "schoolsDeclined": 0 },
            "suggestedRecruitDistricts": [],
            "pauseDistricts": [],
            "districts": [],
            "nextAction": "Consolidate current school portfolio.",
            "disclaimer": "Advisory only."
        }

    core = schools.filter(school_type="core").count()
    client = schools.filter(school_type="client").count()
    
    ssa_done = schools.filter(current_fy_ssa_status="done").count()
    missing_current_ssa = max(0, total - ssa_done)
    current_ssa_pct = round(ssa_done / total * 100, 1) if total else 0.0
    
    prev_ssa_done = SsaRecord.objects.filter(school__in=schools, fy=prev_fy, deleted_at__isnull=True).values("school_id").distinct().count()
    previous_ssa_pct = round(prev_ssa_done / total * 100, 1) if total else 0.0
    
    completed_acts = Activity.objects.filter(deleted_at__isnull=True, fy=fy, status__in=["completed", "ia_verified", "accountant_confirmed"])
    if not scope.country_scope:
        if scope.staff_ids:
            completed_acts = completed_acts.filter(responsible_staff_id__in=scope.staff_ids)
        elif scope.partner_ids:
            completed_acts = completed_acts.filter(assigned_partner_id__in=scope.partner_ids)
        else:
            completed_acts = completed_acts.none()
            
    reached_schools = completed_acts.filter(school__isnull=False).values("school_id").distinct().count()
    reached_pct = round(reached_schools / total * 100, 1) if total else 0.0

    partner_backlog = Activity.objects.filter(deleted_at__isnull=True, fy=fy, delivery_type="partner", status="awaiting_ia_verification").count()
    partner_evidence_pending = Activity.objects.filter(deleted_at__isnull=True, fy=fy, delivery_type="partner", status="evidence_uploaded").count()
    partner_total = Activity.objects.filter(deleted_at__isnull=True, fy=fy, delivery_type="partner").count()
    partner_strain = round((partner_evidence_pending / partner_total * 100), 1) if partner_total else 0.0

    records_curr = {
        r["school_id"]: r
        for r in SsaRecord.objects.filter(school__in=schools, fy=fy, deleted_at__isnull=True).values("id", "school_id", "average_score")
    }
    records_prev = {
        r["school_id"]: r
        for r in SsaRecord.objects.filter(school__in=schools, fy=prev_fy, deleted_at__isnull=True).values("id", "school_id", "average_score")
    }
    
    improved = 0
    declined = 0
    no_change = 0
    for sid in records_curr:
        r_curr = records_curr[sid]
        r_prev = records_prev.get(sid)
        if r_curr and r_prev:
            diff = (r_curr["average_score"] or 0) - (r_prev["average_score"] or 0)
            if diff > 0.05:
                improved += 1
            elif diff < -0.05:
                declined += 1
            else:
                no_change += 1
                
    total_compared = improved + declined + no_change
    impact_ready_pct = round(improved / total_compared * 100, 1) if total_compared > 0 else 0.0

    missing_cluster = schools.filter(Q(cluster_id__isnull=True) | Q(cluster_id="")).count()
    unmatched_owner = schools.filter(Q(account_owner_id__isnull=True) | Q(account_owner_id="")).count()
    duplicates_count = schools.exclude(duplicate_status="none").count()
    missing_enrollment = schools.filter(Q(enrollment__isnull=True) | Q(enrollment__lte=0)).count()
    
    total_gaps = missing_cluster + unmatched_owner + duplicates_count + missing_enrollment
    penalty_pct = min(100, round((total_gaps / total * 25), 1)) if total else 0.0

    readiness_score = max(0, min(100, round(current_ssa_pct - penalty_pct)))
    
    if readiness_score >= 80:
        recommendation = "Continue Recruiting"
        reason = f"Readiness score is {readiness_score}%. Data quality is high and SSA coverage is at {current_ssa_pct}%. Continue recruiting according to target plan."
    elif readiness_score >= 60:
        recommendation = "Recruit Carefully"
        reason = f"Readiness score is {readiness_score}%. Consolidated SSA coverage is good, but some data quality penalties apply. Monitor active portfolios."
    else:
        recommendation = "Pause Recruitment and Support Current Schools"
        reason = f"Readiness score is {readiness_score}%. Considering SSA coverage ({current_ssa_pct}%) and portfolio data quality gaps, focus on current schools before expanding."

    district_list = (
        schools.filter(district_id__isnull=False)
        .values("district_id", "district__name")
        .annotate(total_schools=Count("id"))
    )
    
    ssa_done_by_district = {
        item["district_id"]: item["done_count"]
        for item in schools.filter(district_id__isnull=False)
        .values("district_id")
        .annotate(done_count=Count("id", filter=Q(current_fy_ssa_status="done")))
    }
    
    clustered_by_district = {
        item["district_id"]: item["clustered_count"]
        for item in schools.filter(district_id__isnull=False)
        .values("district_id")
        .annotate(clustered_count=Count("id", filter=Q(cluster_status="clustered")))
    }
    
    reached_by_district = {
        item["school__district_id"]: item["reached_count"]
        for item in completed_acts.filter(school__district_id__isnull=False)
        .values("school__district_id")
        .annotate(reached_count=Count("school_id", distinct=True))
    }
    
    suggested_recruit_districts = []
    pause_districts = []
    districts_data = []
    
    for d in district_list:
        did = d["district_id"]
        dname = d["district__name"]
        dschools = d["total_schools"]
        
        ddone = ssa_done_by_district.get(did, 0)
        dclustered = clustered_by_district.get(did, 0)
        dreached = reached_by_district.get(did, 0)
        
        ssa_pct = round(ddone / dschools * 100) if dschools else 0
        clustered_pct = round(dclustered / dschools * 100) if dschools else 0
        reached_pct = round(dreached / dschools * 100) if dschools else 0
        
        dscore = max(0, min(100, ssa_pct))
        
        if dscore >= 80:
            signal = "expand"
            suggested_recruit_districts.append({
                "districtId": did,
                "district": dname,
                "ssaCompletionPct": ssa_pct,
                "score": dscore
            })
        elif dscore <= 50:
            signal = "pause"
            pause_districts.append({
                "districtId": did,
                "district": dname,
                "ssaCompletionPct": ssa_pct,
                "score": dscore
            })
        else:
            signal = "hold"
            
        districts_data.append({
            "districtId": did,
            "district": dname,
            "schools": dschools,
            "ssaCompletionPct": ssa_pct,
            "clusteredPct": clustered_pct,
            "reachedPct": reached_pct,
            "score": dscore,
            "signal": signal
        })

    return {
        "fy": fy,
        "scope": "country" if scope.country_scope else "team",
        "readinessScore": readiness_score,
        "recommendation": recommendation,
        "reason": reason,
        "capacity": {
            "totalSchools": total,
            "core": core,
            "client": client,
            "reachedPct": reached_pct,
            "partnerPaymentBacklog": partner_backlog,
            "partnerEvidencePending": partner_evidence_pending,
            "partnerStrainPct": partner_strain
        },
        "ssaReadiness": {
            "currentSsaPct": current_ssa_pct,
            "previousSsaPct": previous_ssa_pct,
            "impactReadyPct": impact_ready_pct,
            "missingCurrentSsa": missing_current_ssa
        },
        "dataQuality": {
            "missingCluster": missing_cluster,
            "unmatchedOwner": unmatched_owner,
            "duplicates": duplicates_count,
            "missingEnrollment": missing_enrollment,
            "penaltyPct": penalty_pct
        },
        "impact": {
            "schoolsImproved": improved,
            "schoolsDeclined": declined
        },
        "suggestedRecruitDistricts": suggested_recruit_districts,
        "pauseDistricts": pause_districts,
        "districts": districts_data,
        "nextAction": "Review active portfolios and complete missing current-FY SSAs before initiating new recruitment rounds.",
        "disclaimer": "This is an advisory decision aid based on reported planning metrics. It does not replace manual executive alignment."
    }


def activity_impact_report(principal, query: dict) -> list[dict]:
    from apps.activities.models import Activity
    from apps.activities.services import calculate_activity_impact

    qs = Activity.objects.filter(
        status="completed",
        focus_intervention__isnull=False,
        deleted_at__isnull=True
    ).order_by("-planned_date")

    out = []
    for a in qs[:200]:
        impact = calculate_activity_impact(a)
        out.append({
            "id": a.id,
            "activityType": a.activity_type,
            "plannedDate": a.planned_date.isoformat() if a.planned_date else None,
            "focusIntervention": a.focus_intervention,
            "schoolName": a.school.name if a.school_id else None,
            "clusterName": a.cluster.name if a.cluster_id else None,
            "impact": impact,
        })
    return out


def school_impact(school_id: str, principal) -> dict:
    from apps.activities.models import Activity
    from apps.activities.services import calculate_activity_impact
    from apps.schools.models import School

    school = School.objects.filter(school_id=school_id, deleted_at__isnull=True).first()
    if not school:
        raise NotFoundError("School not found.")

    activities = Activity.objects.filter(
        school=school,
        status="completed",
        deleted_at__isnull=True
    ).order_by("-planned_date")

    improved_count = 0
    declined_count = 0
    no_change_count = 0
    activities_out = []

    for a in activities:
        impact = calculate_activity_impact(a)
        status = impact.get("status")
        if status == "Improved":
            improved_count += 1
        elif status == "Declined":
            declined_count += 1
        elif status == "No Change":
            no_change_count += 1

        activities_out.append({
            "id": a.id,
            "activityType": a.activity_type,
            "plannedDate": a.planned_date.isoformat() if a.planned_date else None,
            "focusIntervention": a.focus_intervention,
            "impact": impact,
        })

    return {
        "schoolId": school.school_id,
        "name": school.name,
        "improvedCount": improved_count,
        "declinedCount": declined_count,
        "noChangeCount": no_change_count,
        "activities": activities_out,
    }


def cluster_impact(cluster_id: str, principal) -> dict:
    from apps.clusters.services import cluster_activity_impact
    from apps.clusters.models import Cluster

    cluster = Cluster.objects.filter(id=cluster_id, deleted_at__isnull=True).first()
    if not cluster:
        raise NotFoundError("Cluster not found.")

    activities_out = cluster_activity_impact(cluster_id, principal)
    improved_count = sum(1 for a in activities_out if a.get("impact", {}).get("status") == "Improved")
    declined_count = sum(1 for a in activities_out if a.get("impact", {}).get("status") == "Declined")
    no_change_count = sum(1 for a in activities_out if a.get("impact", {}).get("status") == "No Change")

    return {
        "clusterId": cluster.id,
        "name": cluster.name,
        "improvedCount": improved_count,
        "declinedCount": declined_count,
        "noChangeCount": no_change_count,
        "activities": activities_out,
    }


__all__ = [
    "dashboard_summary", "leadership_summary", "district_rollups", "coverage_summary",
    "geo_map_districts", "geo_map_district_detail", "school_directory_summary",
    "ssa_performance", "ssa_performance_grouped", "intervention_improvement",
    "support_ssa_correlation", "staff_vs_partner_correlation", "activity_pipeline",
    "contribution_summary", "recruitment_recommendation",
    "activity_impact_report", "school_impact", "cluster_impact",
]
