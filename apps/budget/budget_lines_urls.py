from django.urls import path
from . import views

urlpatterns = [
    path("", views.BudgetLinesListView.as_view(), name="budget-lines-list"),
]
