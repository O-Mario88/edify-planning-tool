"""Performance URL routes — /api/performance/*."""
from django.urls import path

from . import performance_views as pv

urlpatterns = [
    path("my-targets", pv.MyTargetsView.as_view(), name="my-targets"),
    path("team-targets", pv.TeamTargetsView.as_view(), name="team-targets"),
    path("country-targets", pv.CountryTargetsView.as_view(), name="country-targets"),
    path("hr/staff", pv.HrStaffView.as_view(), name="hr-staff"),
    path("hr/risks", pv.HrRisksView.as_view(), name="hr-risks"),
    path("drilldown", pv.DrilldownView.as_view(), name="drilldown"),
]
