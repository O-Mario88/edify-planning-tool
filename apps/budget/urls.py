"""Budget URL routes — /api/budget/* (the cost spine).

Aggregation by period (monthly/quarterly/fy) lives at /api/budgets/* — see
budgets_urls.py.
"""

from django.urls import path

from . import views

urlpatterns = [
    path("cost-settings", views.CostSettingsView.as_view(), name="cost-settings"),
    path(
        "cost-settings/history",
        views.CostSettingsHistoryView.as_view(),
        name="cost-settings-history",
    ),
    path("costing/preview", views.CostingPreviewView.as_view(), name="costing-preview"),
    path(
        "costing/management-preview",
        views.ManagementCostingPreviewView.as_view(),
        name="management-costing-preview",
    ),
    path("rate-cards", views.RateCardsView.as_view(), name="rate-cards"),
    path(
        "rate-cards/<str:card_id>/lines",
        views.RateCardLineView.as_view(),
        name="rate-card-line",
    ),
    path(
        "rate-cards/<str:card_id>/publish",
        views.RateCardPublishView.as_view(),
        name="rate-card-publish",
    ),
    path(
        "activities/<str:activity_id>/cost-review",
        views.ActivityCostReviewView.as_view(),
        name="activity-cost-review",
    ),
    path(
        "cost-reviews/<str:review_id>/decision",
        views.ActivityCostReviewDecisionView.as_view(),
        name="activity-cost-review-decision",
    ),
    path(
        "strategic-reserve",
        views.StrategicReserveView.as_view(),
        name="strategic-reserve",
    ),
    path(
        "strategic-reserve/<str:reserve_id>/activations",
        views.StrategicReserveActivationView.as_view(),
        name="strategic-reserve-activation",
    ),
    path(
        "strategic-reserve/<str:reserve_id>/approve",
        views.StrategicReserveApprovalView.as_view(),
        name="strategic-reserve-approve",
    ),
    path(
        "strategic-reserve/activations/<str:activation_id>/approve",
        views.StrategicReserveActivationApprovalView.as_view(),
        name="strategic-reserve-activation-approve",
    ),
    path("from-schedule", views.BudgetFromScheduleView.as_view(), name="from-schedule"),
    path("weekly", views.BudgetWeeklyView.as_view(), name="weekly"),
    path("board", views.BudgetBoardView.as_view(), name="board"),
]
