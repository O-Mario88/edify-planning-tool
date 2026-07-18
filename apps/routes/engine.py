"""Route Intelligence engine.

The core question is never just "are these schools in the same district?" —
it is: are they close enough to visit in one working day, do coordinates (when
they exist) confirm it, can the staff hit the CD's daily target, and does the
day respect the primary/secondary district rules?

Working day: 08:00–17:00 minus lunch → 8 available field hours.
Route Load = travel + visit_duration × schools + buffer.
Quality score (0–100): same sub-county +30 · coordinates within radius +25 ·
fits the working day +20 · meets CD daily target +15 · no district violation
+10. Bands: 85+ Excellent · 70–84 Good · 50–69 Risky · <50 Not Feasible ·
district-rule violation ⇒ Blocked (overrides everything).

The costing layer (apps.daily_visit_batches) HARD-blocks the district rules at
scheduling time; this layer re-checks them read-only so previews can warn
before submit and health checks can catch legacy data.
"""

from __future__ import annotations


from django.db import transaction

from apps.routes.location import (
    SchoolCoordinateService,
    SchoolLocationParserService,
)
from apps.routes.models import (
    DailyVisitRouteBatch,
    LocationConfidence,
    RouteRecommendation,
    RouteStatus,
    RouteValidationIssue,
)

# ── Working-day + travel constants ───────────────────────────────────────────
WORK_MINUTES = 9 * 60  # 08:00 – 17:00
LUNCH_MINUTES = 60
AVAILABLE_MINUTES = WORK_MINUTES - LUNCH_MINUTES  # 8h of field time
VISIT_MINUTES_PER_SCHOOL = 60
BUFFER_MINUTES = 30
# No-coordinates fallback: per-hop travel estimates from structured grouping.
HOP_SAME_SUBCOUNTY_MIN = 20
HOP_CROSS_SUBCOUNTY_MIN = 45
BASE_TRAVEL_MIN = 30  # start-of-day leg to the first school
COORD_RADIUS_KM = 15  # "coordinates within radius" scoring gate

SCORE_BANDS = (
    (85, RouteStatus.EXCELLENT),
    (70, RouteStatus.GOOD),
    (50, RouteStatus.RISKY),
)


def _classify(score: int, blocked: bool) -> str:
    if blocked:
        return RouteStatus.BLOCKED
    for floor, status in SCORE_BANDS:
        if score >= floor:
            return status
    return RouteStatus.NOT_FEASIBLE


class RouteValidationService:
    """Read-only re-check of the district rules + data prerequisites.
    Returns issue dicts; blocking issues force status=Blocked."""

    @staticmethod
    def validate(schools, *, visit_date=None, responsible_user=None) -> list[dict]:
        issues: list[dict] = []

        # REG-02 — a route can never be scored feasible/Excellent for a date
        # Planning/My Plan would block (Sunday, public holiday, blackout, or
        # the responsible staff member's approved leave).
        if visit_date is not None:
            from apps.core.calendar_policy import (
                SchedulingPolicyService,
                resolve_scheduling_user,
            )

            resp_user = (
                resolve_scheduling_user(responsible_user) if responsible_user else None
            )
            avail = SchedulingPolicyService.check(resp_user, visit_date)
            if avail["status"] == "blocked":
                issues.append(
                    {
                        "code": "calendar_blocked",
                        "severity": "blocking",
                        "message": "This date is blocked by calendar policy: "
                        + " · ".join(avail["blockers"]),
                    }
                )
        unclassified = sorted(
            {
                s.district.name
                for s in schools
                if s.district_id and not s.district.district_type
            }
        )
        if unclassified:
            issues.append(
                {
                    "code": "unclassified_district",
                    "severity": "blocking",
                    "message": f"District(s) not classified primary/secondary yet: {', '.join(unclassified)}. CD/Admin must classify before route approval.",
                }
            )
        types = {
            s.district.district_type
            for s in schools
            if s.district_id and s.district.district_type
        }
        if len(types) > 1:
            issues.append(
                {
                    "code": "mixed_district_types",
                    "severity": "blocking",
                    "message": "Primary district schools mixed with secondary district schools on the same day.",
                }
            )
        district_ids = {s.district_id for s in schools if s.district_id}
        if types == {"secondary"} and len(district_ids) > 1:
            from apps.daily_visit_batches.services import _resolve_group

            if _resolve_group(district_ids) is None:
                issues.append(
                    {
                        "code": "secondary_group_unapproved",
                        "severity": "blocking",
                        "message": "Multiple secondary districts without an approved Secondary Route Group.",
                    }
                )
        no_district = [s.name for s in schools if not s.district_id]
        if no_district:
            issues.append(
                {
                    "code": "missing_district",
                    "severity": "warning",
                    "message": f"No district on record for: {', '.join(no_district[:3])}{'…' if len(no_district) > 3 else ''}.",
                }
            )
        return issues


class RouteQualityScoringService:
    """The 0–100 backend score + Excellent/Good/Risky/Not Feasible/Blocked."""

    @staticmethod
    def score(
        *,
        subcounty_groups: int,
        total_schools: int,
        coords_confirmed: bool,
        coords_used: int,
        fits_day: bool,
        day_load: int,
        meets_target: bool,
        blocked: bool,
        structured_confirmed: bool = False,
    ) -> tuple[int, str]:
        pts = 0
        # Same sub-county match (+30, degrading with spread).
        if total_schools and subcounty_groups <= 1:
            pts += 30
        elif subcounty_groups == 2:
            pts += 18
        elif subcounty_groups == 3:
            pts += 8
        # Coordinates confirm the route (+25). When no real coordinates exist
        # but every school shares one structured sub-county at HIGH confidence,
        # the structured data is the confirmation (+15) — a same-sub-county day
        # still classifies Excellent, while full +25 stays coordinate-only.
        if coords_confirmed:
            pts += 25
        elif structured_confirmed:
            pts += 15
        elif (
            coords_used and total_schools and coords_used >= max(2, total_schools // 2)
        ):
            pts += 12
        # Travel time under threshold / fits the working day (+20; near-miss 8).
        if fits_day:
            pts += 20
        elif day_load and day_load <= AVAILABLE_MINUTES + 60:
            pts += 8
        # Meets the CD daily target (+15).
        if meets_target:
            pts += 15
        # No district rule violation (+10).
        if not blocked:
            pts += 10
        pts = max(0, min(100, pts))
        return pts, _classify(pts, blocked)


class RouteComputation:
    """Shared math for both the persisted batch and the live preview."""

    @staticmethod
    def compute(schools, *, target: int | None) -> dict:
        parsed = [SchoolLocationParserService.resolve(s) for s in schools]
        by_id = {s.id: s for s in schools}

        # Local grouping: structured sub-county first, parsed area label else.
        sub_county_ids = sorted({s.sub_county_id for s in schools if s.sub_county_id})
        area_labels: list[str] = []
        for p in parsed:
            if p["area_label"] and p["area_label"] not in area_labels:
                area_labels.append(p["area_label"])
        groups = len(sub_county_ids) if sub_county_ids else max(1, len(area_labels))

        # Coordinates path — only real per-school points steer distance math.
        points = {
            p["school_id"]: (p["coords"][0], p["coords"][1])
            for p in parsed
            if p["coords"] and p["coords"][2] in ("geo_point", "school")
        }
        coords_used = len(points)
        est_km = None
        max_leg_km = 0.0
        if coords_used >= 2:
            order, est_km = SchoolCoordinateService.best_sequence(points)
            legs = [
                SchoolCoordinateService.haversine_km(points[a], points[b])
                for a, b in zip(order, order[1:])
            ]
            max_leg_km = max(legs) if legs else 0.0
            travel_min = (
                BASE_TRAVEL_MIN + SchoolCoordinateService.travel_minutes_for_km(est_km)
            )
            ordered_ids = order + [sid for sid in by_id if sid not in points]
        else:
            # Structured fallback: hop cost by sub-county relationship.
            ordered_ids = list(by_id)
            hops = max(0, len(schools) - 1)
            same = groups <= 1
            travel_min = BASE_TRAVEL_MIN + hops * (
                HOP_SAME_SUBCOUNTY_MIN if same else HOP_CROSS_SUBCOUNTY_MIN
            )

        n = len(schools)
        visit_min = n * VISIT_MINUTES_PER_SCHOOL
        day_load = travel_min + visit_min + BUFFER_MINUTES
        fits_day = day_load <= AVAILABLE_MINUTES

        coords_confirmed = bool(
            coords_used == n
            and n >= 2
            and est_km is not None
            and max_leg_km <= COORD_RADIUS_KM
        )
        structured_confirmed = bool(
            not coords_confirmed
            and coords_used < 2
            and n >= 2
            and groups <= 1
            and sub_county_ids
            and all(p["confidence"] == LocationConfidence.HIGH for p in parsed)
        )

        # Route confidence = worst school confidence in the day.
        rank = {
            LocationConfidence.HIGH: 0,
            LocationConfidence.MEDIUM: 1,
            LocationConfidence.LOW: 2,
            LocationConfidence.NEEDS_CLEANUP: 3,
        }
        worst = max(
            (p["confidence"] for p in parsed),
            key=lambda c: rank[c],
            default=LocationConfidence.NEEDS_CLEANUP,
        )

        return {
            "parsed": parsed,
            "ordered_ids": ordered_ids,
            "sub_county_ids": sub_county_ids,
            "area_labels": area_labels[:4],
            "groups": groups,
            "coords_used": coords_used,
            "est_km": est_km,
            "travel_min": travel_min,
            "visit_min": visit_min,
            "buffer_min": BUFFER_MINUTES,
            "day_load": day_load,
            "available": AVAILABLE_MINUTES,
            "fits_day": fits_day,
            "coords_confirmed": coords_confirmed,
            "structured_confirmed": structured_confirmed,
            "confidence": worst,
            "meets_target": bool(target and n >= target),
        }

    @staticmethod
    def warnings(schools, comp, issues, *, target: int | None) -> list[str]:
        out = []
        n = len(schools)
        if comp["groups"] >= 3:
            out.append(
                f"Selected schools are spread across {comp['groups']} sub-counties. "
                "Travel time may reduce completion probability."
            )
        if not comp["fits_day"]:
            h, m = divmod(comp["day_load"], 60)
            out.append(
                f"Estimated field load is {h}h {m:02d}m — exceeds the 8h working day. "
                "Reduce schools or split into another day."
            )
        if target and n < target:
            out.append(
                f"CD target is {target} schools per day. You selected {n}. Reason required."
            )
        if target and n >= target and not comp["fits_day"]:
            out.append(
                f"{n} schools selected, but route feasibility is low. "
                "Group schools by same sub-county or nearby area."
            )
        if comp["confidence"] in (
            LocationConfidence.LOW,
            LocationConfidence.NEEDS_CLEANUP,
        ):
            out.append(
                "Location confidence low — verify sub-county before route approval."
            )
        for i in issues:
            if i["severity"] == "blocking":
                out.append(i["message"])
        return out


class RouteRecommendationService:
    """Suggest better groupings from the staff member's own plannable schools."""

    @staticmethod
    def recommend(
        schools, comp, *, responsible_user, target: int | None, visit_date=None
    ) -> list[dict]:
        from apps.schools.models import School

        recs: list[dict] = []
        n = len(schools)
        if not schools:
            return recs
        # Dominant sub-county (by school count).
        counts: dict[str, int] = {}
        for s in schools:
            if s.sub_county_id:
                counts[s.sub_county_id] = counts.get(s.sub_county_id, 0) + 1
        dominant = max(counts, key=counts.get) if counts else None
        dominant_name = (
            next(
                (s.sub_county.name for s in schools if s.sub_county_id == dominant),
                None,
            )
            if dominant
            else None
        )

        candidates = School.objects.none()
        if dominant:
            selected_ids = [s.id for s in schools]
            # Nearby schools in the dominant sub-county; ones still needing
            # SSA first (they benefit most from an extra visit), then the rest.
            candidates = (
                School.objects.filter(sub_county_id=dominant, deleted_at__isnull=True)
                .exclude(id__in=selected_ids)
                .order_by("current_fy_ssa_status", "id")[:3]
            )

        # Scattered day → swap the outlier for a school in the dominant area.
        if comp["groups"] >= 3 and dominant:
            outlier = next(
                (s for s in schools if s.sub_county_id and s.sub_county_id != dominant),
                None,
            )
            swap_in = candidates.first() if candidates else None
            if outlier and swap_in:
                recs.append(
                    {
                        "kind": "swap",
                        "message": f"Replace {outlier.name} with {swap_in.name} — it is closer to the selected {dominant_name} route.",
                        "school_ids": [outlier.id, swap_in.id],
                    }
                )
            else:
                recs.append(
                    {
                        "kind": "split",
                        "message": "Split this day: keep the schools in one sub-county and move the rest to another day.",
                        "school_ids": [],
                    }
                )
        # Below CD target → add nearby schools from the dominant area.
        if target and n < target and dominant:
            addable = list(candidates[: target - n])
            if addable:
                names = ", ".join(a.name for a in addable[:2])
                recs.append(
                    {
                        "kind": "add",
                        "message": f"Add {min(len(addable), target - n)} nearby school(s) from {dominant_name} to reach the daily target (e.g. {names}).",
                        "school_ids": [a.id for a in addable],
                    }
                )
        # Over the day's capacity → reduce.
        if not comp["fits_day"] and n > 1:
            recs.append(
                {
                    "kind": "reduce",
                    "message": "Reduce the number of schools or split into two days — the estimated load exceeds the working day.",
                    "school_ids": [],
                }
            )
        return recs[:3]


class DailyVisitRouteBatchService:
    """Build/rebuild the persisted route batch for one staff member + date.
    Called after every costing-batch change; never raises into the caller."""

    @staticmethod
    def rebuild_for(responsible_user: str, visit_date) -> DailyVisitRouteBatch | None:
        from apps.activities.models import Activity
        from apps.budget.costing_service import active_catalogue
        from apps.daily_visit_batches.models import DailyVisitBatch

        cost_batch = DailyVisitBatch.objects.filter(
            responsible_user=responsible_user, visit_date=visit_date
        ).first()
        acts = Activity.objects.filter(
            deleted_at__isnull=True,
            activity_type="school_visit",
            delivery_type="staff",
        ).exclude(status="cancelled")
        if cost_batch:
            acts = acts.filter(daily_visit_batch=cost_batch)
        else:
            acts = acts.filter(
                responsible_staff_id=responsible_user, scheduled_date__date=visit_date
            )
        schools = [
            a.school
            for a in acts.select_related(
                "school__district", "school__sub_county", "school__parish"
            )
            if a.school_id
        ]
        # Dedup (two visits to the same school on one day is still one stop).
        seen, uniq = set(), []
        for s in schools:
            if s.id not in seen:
                seen.add(s.id)
                uniq.append(s)
        schools = uniq

        if not schools:
            DailyVisitRouteBatch.objects.filter(
                responsible_user=responsible_user, visit_date=visit_date
            ).delete()
            return None

        catalogue = active_catalogue()
        target = catalogue.required_school_visits_per_day if catalogue else 5
        comp = RouteComputation.compute(schools, target=target)
        issues = RouteValidationService.validate(
            schools, visit_date=visit_date, responsible_user=responsible_user
        )
        blocked = any(i["severity"] == "blocking" for i in issues)
        score, status = RouteQualityScoringService.score(
            subcounty_groups=comp["groups"],
            total_schools=len(schools),
            coords_confirmed=comp["coords_confirmed"],
            coords_used=comp["coords_used"],
            fits_day=comp["fits_day"],
            day_load=comp["day_load"],
            meets_target=comp["meets_target"],
            blocked=blocked,
            structured_confirmed=comp["structured_confirmed"],
        )
        warnings = RouteComputation.warnings(schools, comp, issues, target=target)
        recs = RouteRecommendationService.recommend(
            schools,
            comp,
            responsible_user=responsible_user,
            target=target,
            visit_date=visit_date,
        )

        district = next((s.district for s in schools if s.district_id), None)
        dtypes = {
            s.district.district_type
            for s in schools
            if s.district_id and s.district.district_type
        }

        with transaction.atomic():
            batch, _ = DailyVisitRouteBatch.objects.update_or_create(
                responsible_user=responsible_user,
                visit_date=visit_date,
                defaults={
                    "district_type": next(iter(dtypes)) if len(dtypes) == 1 else None,
                    "district": district,
                    "secondary_district_group": cost_batch.secondary_district_group
                    if cost_batch
                    else None,
                    "cost_batch": cost_batch,
                    "school_ids": comp["ordered_ids"],
                    "school_count": len(schools),
                    "area_labels": comp["area_labels"],
                    "sub_county_ids": comp["sub_county_ids"],
                    "coords_used": comp["coords_used"],
                    "est_distance_km": comp["est_km"],
                    "est_travel_minutes": comp["travel_min"],
                    "visit_minutes": comp["visit_min"],
                    "buffer_minutes": comp["buffer_min"],
                    "day_load_minutes": comp["day_load"],
                    "available_minutes": comp["available"],
                    "feasible": comp["fits_day"],
                    "quality_score": score,
                    "status": status,
                    "confidence": comp["confidence"],
                    "warnings": warnings,
                    "target_snapshot": target,
                },
            )
            batch.issues.all().delete()
            RouteValidationIssue.objects.bulk_create(
                [
                    RouteValidationIssue(
                        batch=batch,
                        code=i["code"],
                        severity=i["severity"],
                        message=i["message"],
                    )
                    for i in issues
                ]
            )
            batch.recommendations.all().delete()
            RouteRecommendation.objects.bulk_create(
                [
                    RouteRecommendation(
                        batch=batch,
                        kind=r["kind"],
                        message=r["message"],
                        school_ids=r["school_ids"],
                    )
                    for r in recs
                ]
            )
        return batch


class PlanningRoutePreviewService:
    """Live route preview for the scheduling drawer — same math as the batch,
    nothing persisted except refreshed per-school location confidence."""

    @staticmethod
    def preview(
        *, school_ids: list[str], responsible_user: str, visit_date=None
    ) -> dict:
        from apps.budget.costing_service import active_catalogue
        from apps.daily_visit_batches.pricing import compute_daily_pool
        from apps.schools.models import School

        schools = list(
            School.objects.filter(
                school_id__in=school_ids, deleted_at__isnull=True
            ).select_related("district", "sub_county", "parish")
        ) or list(
            School.objects.filter(
                id__in=school_ids, deleted_at__isnull=True
            ).select_related("district", "sub_county", "parish")
        )
        if not schools:
            return {"ok": False, "error": "No valid schools selected."}

        catalogue = active_catalogue()
        target = catalogue.required_school_visits_per_day if catalogue else 5
        comp = RouteComputation.compute(schools, target=target)
        issues = RouteValidationService.validate(
            schools, visit_date=visit_date, responsible_user=responsible_user
        )
        blocked = any(i["severity"] == "blocking" for i in issues)
        score, status = RouteQualityScoringService.score(
            subcounty_groups=comp["groups"],
            total_schools=len(schools),
            coords_confirmed=comp["coords_confirmed"],
            coords_used=comp["coords_used"],
            fits_day=comp["fits_day"],
            day_load=comp["day_load"],
            meets_target=comp["meets_target"],
            blocked=blocked,
            structured_confirmed=comp["structured_confirmed"],
        )
        warnings = RouteComputation.warnings(schools, comp, issues, target=target)
        recs = RouteRecommendationService.recommend(
            schools,
            comp,
            responsible_user=responsible_user,
            target=target,
            visit_date=visit_date,
        )

        # Honest cost-per-school from the real catalogue pool (None when the
        # catalogue/district data can't price the day yet).
        cost_per_school = None
        dtypes = {
            s.district.district_type
            for s in schools
            if s.district_id and s.district.district_type
        }
        if catalogue and len(dtypes) == 1:
            try:
                from apps.budget.costing_service import _rate_card

                rates, _ = _rate_card(catalogue)
                pool = compute_daily_pool(rates, next(iter(dtypes)))
                cost_per_school = sum(pool.values()) // max(1, len(schools))
            except Exception:  # noqa: BLE001 — missing rates → no fake price
                cost_per_school = None

        def hm(minutes):
            h, m = divmod(int(minutes), 60)
            return f"{h}h {m:02d}m"

        detected = (
            " / ".join(comp["area_labels"])
            if comp["area_labels"]
            else (
                schools[0].district.name if schools[0].district_id else "Unknown area"
            )
        )
        return {
            "ok": True,
            "status": status,
            "score": score,
            "school_count": len(schools),
            "detected_area": detected,
            "district": next((s.district.name for s in schools if s.district_id), None),
            "groups": comp["groups"],
            "confidence": comp["confidence"],
            "coords_used": comp["coords_used"],
            "est_distance_km": comp["est_km"],
            "travel_label": hm(comp["travel_min"]),
            "visit_label": hm(comp["visit_min"]),
            "load_label": hm(comp["day_load"]),
            "available_label": hm(comp["available"]),
            "feasible": comp["fits_day"],
            "meets_target": comp["meets_target"],
            "target": target,
            "cost_per_school": cost_per_school,
            "warnings": warnings,
            "recommendations": recs,
            "blocked": blocked,
        }


class RouteIntelligenceService:
    """Facade for dashboards: aggregate real route batches for a set of staff."""

    @staticmethod
    def team_summary(user_ids: list[str], *, since=None) -> dict:
        qs = DailyVisitRouteBatch.objects.filter(responsible_user__in=user_ids)
        if since:
            qs = qs.filter(visit_date__gte=since)
        batches = list(qs)
        if not batches:
            return {
                "has_batches": False,
                "avg_score": None,
                "counts": {},
                "batches": [],
            }
        counts: dict[str, int] = {}
        for b in batches:
            counts[b.status] = counts.get(b.status, 0) + 1
        return {
            "has_batches": True,
            "avg_score": round(sum(b.quality_score for b in batches) / len(batches)),
            "counts": counts,
            "batches": batches,
        }


__all__ = [
    "AVAILABLE_MINUTES",
    "VISIT_MINUTES_PER_SCHOOL",
    "BUFFER_MINUTES",
    "COORD_RADIUS_KM",
    "RouteValidationService",
    "RouteQualityScoringService",
    "RouteComputation",
    "RouteRecommendationService",
    "DailyVisitRouteBatchService",
    "PlanningRoutePreviewService",
    "RouteIntelligenceService",
]
