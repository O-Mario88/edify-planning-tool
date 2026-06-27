"""Budgets URL routes — /api/budgets/* (program + admin aggregation by period)."""
from django.urls import path

from . import views

urlpatterns = [
    path("monthly", views.MonthlyBudgetView.as_view(), name="budgets-monthly"),
    path("quarterly", views.QuarterlyBudgetView.as_view(), name="budgets-quarterly"),
    path("fy", views.FyBudgetView.as_view(), name="budgets-fy"),
]
