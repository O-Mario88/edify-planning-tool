from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages

from apps.clusters.services import (
    list_clusters,
    cluster_schools,
    cluster_detail,
    cluster_weakest_interventions,
    cluster_intervention_summary,
    cluster_activity_impact
)

@login_required(login_url="/login")
def cluster_list_view(request):
    clusters = list_clusters(request.user)
    context = {
        "clusters": clusters,
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
