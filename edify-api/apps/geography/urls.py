"""Geography URL routes — /api/geography/*."""
from django.urls import path

from . import views

app_name = "geography"

urlpatterns = [
    path("regions", views.RegionListView.as_view(), name="regions"),
    path("districts", views.DistrictListView.as_view(), name="districts"),
    path("sub-counties", views.SubCountyListView.as_view(), name="sub-counties"),
    path("parishes", views.ParishListView.as_view(), name="parishes"),
    path("villages", views.VillageListView.as_view(), name="villages"),
]
