"""Budget URL routes — /api/budget/* (the cost spine).

Aggregation by period (monthly/quarterly/fy) lives at /api/budgets/* — see
budgets_urls.py.
"""
from django.urls import path

from . import views

urlpatterns = [
    path("cost-settings", views.CostSettingsView.as_view(), name="cost-settings"),
    path("cost-settings/history", views.CostSettingsHistoryView.as_view(), name="cost-settings-history"),
    path("costing/preview", views.CostingPreviewView.as_view(), name="costing-preview"),
    path("from-schedule", views.BudgetFromScheduleView.as_view(), name="from-schedule"),
    path("weekly", views.BudgetWeeklyView.as_view(), name="weekly"),
    path("board", views.BudgetBoardView.as_view(), name="board"),
]
