from django.urls import path

from . import views

urlpatterns = [
    path("options", views.AssignmentOptionsView.as_view(), name="options"),
    path("capacity", views.AssignmentCapacityView.as_view(), name="capacity"),
]
