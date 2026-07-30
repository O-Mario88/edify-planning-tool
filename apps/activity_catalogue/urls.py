from django.urls import path

from .views import (
    CatalogueDetailView,
    CatalogueLifecycleView,
    CatalogueListView,
    CatalogueRecommendationsView,
    CatalogueProjectMappingView,
    CatalogueAnalyticsView,
)


urlpatterns = [
    path("", CatalogueListView.as_view()),
    path("recommendations", CatalogueRecommendationsView.as_view()),
    path("analytics", CatalogueAnalyticsView.as_view()),
    path("<str:item_id>", CatalogueDetailView.as_view()),
    path("<str:item_id>/lifecycle", CatalogueLifecycleView.as_view()),
    path("<str:item_id>/projects", CatalogueProjectMappingView.as_view()),
]
