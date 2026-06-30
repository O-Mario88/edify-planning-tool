from django.db.models import Q, Sum, Count
from apps.accounts.models import StaffProfile, User
from apps.activities.models import Activity, ActivityScheduleCostLine
from apps.geography.models import District

VISIT_TYPES = {
    "school_visit", "follow_up_visit", "coaching_visit", "in_school_support", "core_visit"
}

class MonthlyFundAllocationService:
    @staticmethod
    def get_monthly_allocation(month_num: int, fy: str, region_id: str = None, district_id: str = None, search_q: str = None, page: int = 1, per_page: int = 10):
        # 1. Base query for staff profiles who have user profiles
        staff_qs = StaffProfile.objects.filter(deleted_at__isnull=True).select_related("user")
        
        if district_id:
            staff_qs = staff_qs.filter(primary_district_id=district_id)
        if search_q:
            staff_qs = staff_qs.filter(Q(user__name__icontains=search_q) | Q(user__email__icontains=search_q))
        if region_id:
            districts_in_region = District.objects.filter(region_id=region_id).values_list("id", flat=True)
            staff_qs = staff_qs.filter(primary_district_id__in=districts_in_region)
            
        staff_qs = staff_qs.order_by("user__name")
        total_staff_count = staff_qs.count()
        
        # Paginate staff rows
        start_idx = (page - 1) * per_page
        end_idx = start_idx + per_page
        paginated_staff = list(staff_qs[start_idx:end_idx])
        
        # Get list of all matching staff IDs for total stats
        all_staff_ids = [s.user.user_id for s in staff_qs]
        
        # 2. Get cost lines for all these staff in the month & FY
        cost_lines = ActivityScheduleCostLine.objects.filter(
            fiscal_year=fy,
            month=month_num,
            responsible_user__in=all_staff_ids
        ).select_related("activity")
        
        # Build category mappings and totals
        # Category classification
        activity_categories = {}
        activity_amounts = {}
        activity_staff = {}
        
        for line in cost_lines:
            act_id = line.activity_id
            if act_id not in activity_categories:
                act = line.activity
                act_type = act.activity_type
                delivery = act.delivery_type
                
                # Classify
                if act_type == "ssa_activity":
                    cat = "ssa"
                elif act_type in ["cluster_training", "training", "school_improvement_training", "core_training", "cluster_meeting"]:
                    cat = "cluster_training"
                elif act_type == "partner_activity" or (act_type in ["training", "school_improvement_training", "core_training"] and delivery == "partner"):
                    cat = "partner_in_school_training"
                elif act_type in VISIT_TYPES and delivery == "partner":
                    cat = "partner_visits"
                else:
                    cat = "staff_visits"
                    
                activity_categories[act_id] = cat
                activity_amounts[act_id] = 0
                activity_staff[act_id] = line.responsible_user
                
            activity_amounts[act_id] += line.amount

        # Initialize data structures for CCEOs
        staff_data = {}
        for s in paginated_staff:
            staff_data[s.user.user_id] = {
                "user_id": s.user.user_id,
                "name": s.user.name,
                "staff_visits": {"count": 0, "unit_cost": 0, "total": 0},
                "partner_visits": {"count": 0, "unit_cost": 0, "total": 0},
                "ssa": {"count": 0, "unit_cost": 0, "total": 0},
                "cluster_training": {"count": 0, "unit_cost": 0, "total": 0},
                "partner_in_school_training": {"count": 0, "unit_cost": 0, "total": 0},
                "total_allocation": 0
            }
            
        # We also calculate totals for ALL filtered staff for KPI cards and table totals
        all_staff_data = {}
        for s in staff_qs:
            all_staff_data[s.user.user_id] = {
                "user_id": s.user.user_id,
                "name": s.user.name,
                "staff_visits": {"count": 0, "unit_cost": 0, "total": 0},
                "partner_visits": {"count": 0, "unit_cost": 0, "total": 0},
                "ssa": {"count": 0, "unit_cost": 0, "total": 0},
                "cluster_training": {"count": 0, "unit_cost": 0, "total": 0},
                "partner_in_school_training": {"count": 0, "unit_cost": 0, "total": 0},
                "total_allocation": 0
            }
            
        grand_totals = {
            "staff_visits": {"count": 0, "total": 0, "unit_cost": 0},
            "partner_visits": {"count": 0, "total": 0, "unit_cost": 0},
            "ssa": {"count": 0, "total": 0, "unit_cost": 0},
            "cluster_training": {"count": 0, "total": 0, "unit_cost": 0},
            "partner_in_school_training": {"count": 0, "total": 0, "unit_cost": 0},
            "total_allocation": 0
        }
        
        # Group activity counts and values by staff
        # staff_id -> category -> list of activity_ids
        staff_activities = {}
        staff_category_totals = {}
        
        for act_id, cat in activity_categories.items():
            u_id = activity_staff[act_id]
            if u_id not in staff_activities:
                staff_activities[u_id] = {
                    "staff_visits": set(),
                    "partner_visits": set(),
                    "ssa": set(),
                    "cluster_training": set(),
                    "partner_in_school_training": set()
                }
                staff_category_totals[u_id] = {
                    "staff_visits": 0,
                    "partner_visits": 0,
                    "ssa": 0,
                    "cluster_training": 0,
                    "partner_in_school_training": 0
                }
            staff_activities[u_id][cat].add(act_id)
            staff_category_totals[u_id][cat] += activity_amounts[act_id]
            
        # Populate paginated CCEO rows
        for u_id, s_info in staff_data.items():
            if u_id in staff_activities:
                for cat in ["staff_visits", "partner_visits", "ssa", "cluster_training", "partner_in_school_training"]:
                    act_ids = staff_activities[u_id][cat]
                    cnt = len(act_ids)
                    tot = staff_category_totals[u_id][cat]
                    unit = tot // cnt if cnt > 0 else 0
                    
                    s_info[cat] = {
                        "count": cnt,
                        "unit_cost": unit,
                        "total": tot
                    }
                    s_info["total_allocation"] += tot
                    
        # Populate all CCEO data rows for insights calculation
        for u_id, s_info in all_staff_data.items():
            if u_id in staff_activities:
                for cat in ["staff_visits", "partner_visits", "ssa", "cluster_training", "partner_in_school_training"]:
                    act_ids = staff_activities[u_id][cat]
                    cnt = len(act_ids)
                    tot = staff_category_totals[u_id][cat]
                    unit = tot // cnt if cnt > 0 else 0
                    s_info[cat] = {
                        "count": cnt,
                        "unit_cost": unit,
                        "total": tot
                    }
                    s_info["total_allocation"] += tot

        # Calculate grand totals across ALL filtered staff
        for u_id in all_staff_data.keys():
            if u_id in staff_activities:
                for cat in ["staff_visits", "partner_visits", "ssa", "cluster_training", "partner_in_school_training"]:
                    act_ids = staff_activities[u_id][cat]
                    tot = staff_category_totals[u_id][cat]
                    grand_totals[cat]["count"] += len(act_ids)
                    grand_totals[cat]["total"] += tot
                    grand_totals["total_allocation"] += tot

        # Calculate average/unit cost in grand totals row
        for cat in ["staff_visits", "partner_visits", "ssa", "cluster_training", "partner_in_school_training"]:
            cnt = grand_totals[cat]["count"]
            tot = grand_totals[cat]["total"]
            grand_totals[cat]["unit_cost"] = tot // cnt if cnt > 0 else 0
            
        rows = list(staff_data.values())
        rows_all = list(all_staff_data.values())
        
        return {
            "rows": rows,
            "rows_all": rows_all,
            "grand_totals": grand_totals,
            "total_staff_count": total_staff_count,
            "total_activities_count": len(activity_categories),
        }

    @staticmethod
    def calculate_insights(rows_all, grand_totals, total_staff_count):
        if not rows_all or total_staff_count == 0 or grand_totals["total_allocation"] == 0:
            return {
                "highest_cost_staff": None,
                "largest_cluster_budget": None,
                "partner_cost_share": 0.0,
                "top_cost_category": {"name": "None", "total": 0, "pct": 0},
                "average_allocation": 0,
            }
            
        # Highest Cost Staff
        highest_staff = max(rows_all, key=lambda r: r["total_allocation"])
        highest_staff_pct = (highest_staff["total_allocation"] / grand_totals["total_allocation"] * 100)
        
        # Largest Cluster Training CCEO/staff
        largest_cluster_staff = max(rows_all, key=lambda r: r["cluster_training"]["total"])
        largest_cluster_pct = (largest_cluster_staff["cluster_training"]["total"] / grand_totals["cluster_training"]["total"] * 100) if grand_totals["cluster_training"]["total"] > 0 else 0
        
        # Partner Cost Share
        partner_total = grand_totals["partner_visits"]["total"] + grand_totals["partner_in_school_training"]["total"]
        partner_share = (partner_total / grand_totals["total_allocation"] * 100)
        
        # Top Cost Category
        cats = {
            "Staff Visits": grand_totals["staff_visits"]["total"],
            "Partner Visits": grand_totals["partner_visits"]["total"],
            "SSA": grand_totals["ssa"]["total"],
            "Cluster Training": grand_totals["cluster_training"]["total"],
            "Partner In-School Training": grand_totals["partner_in_school_training"]["total"],
        }
        top_cat = max(cats, key=cats.get)
        top_cat_pct = (cats[top_cat] / grand_totals["total_allocation"] * 100)
        
        # Average allocation
        avg_allocation = grand_totals["total_allocation"] // total_staff_count
        
        return {
            "highest_cost_staff": {
                "name": highest_staff["name"],
                "total": highest_staff["total_allocation"],
                "pct": round(highest_staff_pct, 1)
            },
            "largest_cluster_budget": {
                "name": largest_cluster_staff["name"],
                "total": largest_cluster_staff["cluster_training"]["total"],
                "pct": round(largest_cluster_pct, 1)
            },
            "partner_cost_share": round(partner_share, 1),
            "top_cost_category": {
                "name": top_cat,
                "total": cats[top_cat],
                "pct": round(top_cat_pct, 1)
            },
            "average_allocation": avg_allocation
        }
