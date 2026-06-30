from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages

from apps.clusters.services import (
    list_clusters,
    cluster_schools,
    cluster_detail,
    cluster_weakest_interventions,
    cluster_intervention_summary,
    cluster_activity_impact,
    cluster_planning
)

@login_required(login_url="/login")
def cluster_list_view(request):
    clusters = list_clusters(request.user)
    planning_data = cluster_planning(request.user)
    
    total_clusters = len(clusters)
    total_schools = sum(c.get("schoolCount", 0) for c in clusters)
    
    # Calculate KPIs from planning data
    not_met_this_quarter = sum(1 for p in planning_data if not p.get("metThisQuarter", True))
    needing_training = sum(1 for p in planning_data if p.get("schoolsNotTrained", 0) > 0)
    without_ssa = sum(1 for c in clusters if c.get("schoolsWithSsa", 0) < c.get("schoolCount", 0))
    
    kpis = {
        "total_clusters": total_clusters,
        "total_schools": total_schools,
        "not_met_this_quarter": not_met_this_quarter,
        "needing_training": needing_training,
        "without_ssa": without_ssa,
        "avg_ssa": 5.8,  # Placeholder, should compute actual
        "weakest_intervention": "Leadership", # Placeholder
        "pending_activities": 24, # Placeholder
    }
    
    # Merge planning data into clusters for the list
    planning_map = {p["id"]: p for p in planning_data}
    for c in clusters:
        c["planning"] = planning_map.get(c["id"], {})
        
    context = {
        "clusters": clusters,
        "kpis": kpis,
    }
    return render(request, "pages/clusters/index.html", context)

@login_required(login_url="/login")
def cluster_schools_partial(request, cluster_id):
    schools = cluster_schools(cluster_id, request.user)
    context = {
        "schools": schools,
        "cluster_id": cluster_id,
    }
    return render(request, "partials/cluster_schools_dropdown.html", context)

@login_required(login_url="/login")
def cluster_detail_view(request, cluster_id):
    try:
        detail = cluster_detail(cluster_id, request.user)
        weakest = cluster_weakest_interventions(cluster_id, request.user)
        summary = cluster_intervention_summary(cluster_id, request.user)
        impact = cluster_activity_impact(cluster_id, request.user)
        schools = cluster_schools(cluster_id, request.user)
    except Exception as e:
        messages.error(request, f"Error loading cluster details: {e}")
        return redirect("/clusters")

    context = {
        "cluster": detail,
        "weakest_interventions": weakest,
        "intervention_summary": summary,
        "activity_impact": impact,
        "schools": schools,
    }
    return render(request, "pages/clusters/detail.html", context)
