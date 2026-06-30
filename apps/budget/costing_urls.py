from django.urls import path
from . import views

urlpatterns = [
    path("preview", views.CostingPreviewView.as_view(), name="costing-preview-direct"),
]
