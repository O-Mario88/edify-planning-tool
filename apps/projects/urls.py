from django.urls import path

from . import views

urlpatterns = [
    path("", views.ProjectListView.as_view(), name="list"),
    path("<str:project_id>", views.ProjectDetailView.as_view(), name="detail"),
    path("<str:project_id>/impact", views.ProjectImpactView.as_view(), name="impact"),
    path(
        "<str:project_id>/partners",
        views.ProjectPartnersView.as_view(),
        name="partners",
    ),
    path(
        "<str:project_id>/partners/<str:partner_id>",
        views.ProjectPartnerRemoveView.as_view(),
        name="remove-partner",
    ),
    path(
        "<str:project_id>/schools",
        views.ProjectSchoolsAssignView.as_view(),
        name="assign-school",
    ),
    path(
        "<str:project_id>/schools/<str:school_id>",
        views.ProjectSchoolsRemoveView.as_view(),
        name="remove-school",
    ),
]
