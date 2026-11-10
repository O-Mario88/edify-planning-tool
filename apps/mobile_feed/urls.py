"""Screen feed routes, mounted at /api/mobile/v1/*."""

from django.urls import path

from . import views

urlpatterns = [
    path("home", views.HomeFeedView.as_view(), name="mobile-feed-home"),
    path(
        "home/queue", views.HomeQueueFeedView.as_view(), name="mobile-feed-home-queue"
    ),
    path(
        "home/todo-figures",
        views.HomeTodoFiguresFeedView.as_view(),
        name="mobile-feed-home-todo-figures",
    ),
    path(
        "navigation", views.NavigationFeedView.as_view(), name="mobile-feed-navigation"
    ),
    path(
        "school-directory",
        views.SchoolDirectoryFeedView.as_view(),
        name="mobile-feed-school-directory",
    ),
    path(
        "schools/bulk-assign-cluster",
        views.BulkAssignClusterFeedView.as_view(),
        name="mobile-feed-bulk-assign-cluster",
    ),
    path(
        "schools/bulk-assign-project",
        views.BulkAssignProjectFeedView.as_view(),
        name="mobile-feed-bulk-assign-project",
    ),
    path(
        "schools/<str:school_id>/add-to-cluster",
        views.AddToClusterFeedView.as_view(),
        name="mobile-feed-add-to-cluster",
    ),
    path(
        "drawers/options",
        views.DrawerOptionsFeedView.as_view(),
        name="mobile-feed-drawer-options",
    ),
    path(
        "schools/<str:school_id>/drawers/<str:kind>",
        views.SchoolDrawerFeedView.as_view(),
        name="mobile-feed-school-drawer",
    ),
    path(
        "schools/<str:school_id>/planning/<str:kind>",
        views.PlanningDrawerFeedView.as_view(),
        name="mobile-feed-planning-drawer",
    ),
    path("my-plan", views.MyPlanFeedView.as_view(), name="mobile-feed-my-plan"),
    path("page", views.PageFeedView.as_view(), name="mobile-feed-page"),
    path("drawer", views.DrawerFeedView.as_view(), name="mobile-feed-drawer"),
    path(
        "planning/training-capacity",
        views.TrainingCapacityFeedView.as_view(),
        name="mobile-feed-training-capacity",
    ),
    path(
        "schools/<str:school_id>/profile",
        views.SchoolProfileFeedView.as_view(),
        name="mobile-feed-school-profile",
    ),
    path(
        "schools/<str:school_id>/add-to-project",
        views.AddToProjectFeedView.as_view(),
        name="mobile-feed-add-to-project",
    ),
]
