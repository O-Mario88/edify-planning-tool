from django.urls import path

from . import views

urlpatterns = [
    path("", views.MyPlanView.as_view(), name="my-plan"),
]
