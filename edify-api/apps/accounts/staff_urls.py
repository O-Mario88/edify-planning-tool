"""Staff URL routes — /api/staff/* (roster + supervisor assignment)."""
from django.urls import path

from . import staff_views

urlpatterns = [
    path("", staff_views.StaffListView.as_view(), name="staff-list"),
    path("<str:staff_id>/assign-supervisor", staff_views.AssignSupervisorView.as_view(), name="assign-supervisor"),
]
