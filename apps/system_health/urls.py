from django.urls import path

from . import views

urlpatterns = [
    path("", views.SystemHealthView.as_view(), name="report"),
]
