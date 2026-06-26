from django.urls import path

from . import views

urlpatterns = [
    path("health", views.SecurityHealthView.as_view(), name="health"),
]
