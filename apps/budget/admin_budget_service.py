"""Admin budget allocation service — CD monthly plan retrieval and grouping."""
from __future__ import annotations

from apps.monthly_work_plan.models import MonthlyWorkPlanBudget, MonthlyWorkPlanBudgetStatus

class AdminBudgetAllocationService:
    @staticmethod
    def get_admin_budget_allocation(month_num: int, fy: str) -> dict:
        """Fetch and aggregate administrative budget lines for a month & FY."""
        # Calculate month key: YYYY-MM
        fy_year = int(fy)
        if month_num >= 10:
            year_int = fy_year - 1
        else:
            year_int = fy_year
            
        month_key = f"{year_int}-{month_num:02d}"
        
        mwp = MonthlyWorkPlanBudget.objects.filter(fy=fy, month_key=month_key).first()
        if not mwp:
            return {
                "exists": False,
                "approved": False,
                "status_label": "No Plan Found",
                "status_class": "bg-rose-50 text-rose-700 border-rose-250",
                "planned_total": 0,
                "allocated_total": 0,
                "total": 0,
                "lines": [],
            }
            
        # Determine approval status based on choices
        status = mwp.status
        approved = status in [
            MonthlyWorkPlanBudgetStatus.APPROVED_BY_RVP.value,
            MonthlyWorkPlanBudgetStatus.SENT_TO_ACCOUNTANT.value,
            MonthlyWorkPlanBudgetStatus.DISBURSED.value,
            MonthlyWorkPlanBudgetStatus.CLOSED.value
        ]
        
        status_label = mwp.get_status_display()
        if not approved:
            status_class = "bg-amber-50 text-amber-700 border-amber-250 animate-pulse"
        else:
            status_class = "bg-emerald-50 text-emerald-700 border-emerald-250"
            
        lines = list(mwp.admin_lines.all())
        
        # Calculate planned vs allocated
        # Under policy: CD planned lines are sum of all lines; allocated is sum if approved
        planned_total = sum(l.total_cost for l in lines)
        allocated_total = planned_total if approved else 0
        total = allocated_total
        
        serialized_lines = []
        for l in lines:
            serialized_lines.append({
                "id": l.id,
                "cost_category": l.cost_category.replace("_", " ").title(),
                "description": l.description,
                "quantity": float(l.quantity),
                "unit_cost": l.unit_cost,
                "total_cost": l.total_cost,
                "justification": l.justification or "None",
                "created_by": l.created_by_user_id,
                "status": "Approved" if approved else "Pending",
            })
            
        return {
            "exists": True,
            "approved": approved,
            "status_label": status_label,
            "status_class": status_class,
            "planned_total": planned_total,
            "allocated_total": allocated_total,
            "total": total,
            "lines": serialized_lines,
        }
