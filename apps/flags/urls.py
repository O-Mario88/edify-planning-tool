from django.urls import path

from . import views

urlpatterns = [
    path("", views.FlagListRaiseView.as_view(), name="list"),
    path("program-leads", views.FlagProgramLeadsView.as_view(), name="program-leads"),
    path("<str:flag_id>", views.FlagUpdateView.as_view(), name="update"),
]
