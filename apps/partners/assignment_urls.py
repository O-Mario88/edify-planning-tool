from django.urls import path

from .views import PartnerAssignmentEligibleActivitiesView


urlpatterns = [
    path(
        "<str:assignment_id>/eligible-activities",
        PartnerAssignmentEligibleActivitiesView.as_view(),
        name="eligible-activities",
    ),
]
