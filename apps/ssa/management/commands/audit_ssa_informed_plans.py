"""Audit, and optionally repair, how SSA informed the platform's plans are.

    python manage.py audit_ssa_informed_plans                 # report only
    python manage.py audit_ssa_informed_plans --fy 2027
    python manage.py audit_ssa_informed_plans --generate      # record missing recommendations
    python manage.py audit_ssa_informed_plans --stamp         # judge unstamped live plans

The report answers the owner's question (2026-09-13) — are school activity
plans informed by the SSA? — for every live plan: school visits, trainings,
cluster meetings and the rest, by alignment verdict and by activity type. It
also reports the recommendation lifecycle: schools whose latest confirmed SSA
never produced recorded recommendations, and recommendations still waiting on
a plan.

``--generate`` records recommendations for every school whose latest confirmed
assessment has none (idempotent: generation converges on the need's key).
``--stamp`` judges live plans that were created before plans were judged at
planning time, against the SSA as it stands today, and links them to the
recommendations they answer. Completed history is never re-judged: what
informed a finished plan is what was known when it was made.
"""

from __future__ import annotations

from collections import Counter, defaultdict

from django.core.management.base import BaseCommand

from apps.core.fy import get_operational_fy

LIVE_PLAN_STATUSES = (
    "planned",
    "scheduled",
    "assigned_to_partner",
    "partner_scheduled",
    "awaiting_owner_approval",
    "in_progress",
    "completion_started",
)


class Command(BaseCommand):
    help = "Report how SSA informed live plans are; optionally backfill recommendations and verdicts."

    def add_arguments(self, parser):
        parser.add_argument("--fy", default=None, help="Fiscal year (default: operational FY).")
        parser.add_argument(
            "--generate",
            action="store_true",
            help="Record recommendations for schools whose latest confirmed SSA has none.",
        )
        parser.add_argument(
            "--stamp",
            action="store_true",
            help="Judge live plans that carry no verdict and link their recommendations.",
        )
        parser.add_argument(
            "--limit", type=int, default=0, help="Stop after this many schools or plans."
        )

    def handle(self, *args, **options):
        fy = options["fy"] or get_operational_fy()
        if options["generate"]:
            self._generate(fy, options["limit"])
        if options["stamp"]:
            self._stamp(fy, options["limit"])
        self._report(fy)

    # ── Recommendations ──────────────────────────────────────────────────────
    def _generate(self, fy: str, limit: int) -> None:
        from apps.ssa.recommendation_service import sync_recommendations

        result = sync_recommendations(fy=fy, limit=limit or None)
        self.stdout.write(
            f"Recommendations: {result['created']} created, {result['refreshed']} "
            f"refreshed across {result['schools']} school(s); {result['linked']} "
            "linked to live plans."
        )

    # ── Verdicts ─────────────────────────────────────────────────────────────
    def _stamp(self, fy: str, limit: int) -> None:
        from apps.activities.models import Activity
        from apps.ssa import plan_alignment

        plans = (
            Activity.objects.filter(
                deleted_at__isnull=True, fy=fy, status__in=LIVE_PLAN_STATUSES
            )
            .filter(ssa_alignment="")
            .select_related("school", "catalogue_item")
            .order_by("planned_date", "id")
        )
        stamped = linked = 0
        for activity in plans.iterator(chunk_size=200):
            modes = (
                set(
                    activity.catalogue_item.intervention_mappings.filter(
                        active=True
                    ).values_list("mapping_mode", flat=True)
                )
                if activity.catalogue_item_id
                else set()
            )
            evidence = plan_alignment.assess(
                activity_type=activity.activity_type,
                focus=activity.focus_intervention,
                mapping_modes=modes,
                school=activity.school,
                cluster_id=None if activity.school_id else activity.cluster_id,
                focus_source="planner",
                collects_ssa=activity.ssa_collection_expected,
            )
            evidence.evidence["backfilled"] = True
            plan_alignment.stamp(activity, evidence, link=False)
            linked += plan_alignment.link_recommendations(activity)
            stamped += 1
            if limit and stamped >= limit:
                break
        self.stdout.write(
            f"Verdicts: {stamped} live plan(s) judged, {linked} recommendation(s) linked."
        )

    # ── Report ───────────────────────────────────────────────────────────────
    def _report(self, fy: str) -> None:
        from apps.activities.models import Activity
        from apps.schools.models import School
        from apps.ssa.models import SsaRecord
        from apps.ssa.plan_alignment import INFORMED, SsaAlignment
        from apps.ssa.recommendation_models import SsaRecommendation

        live = Activity.objects.filter(
            deleted_at__isnull=True,
            fy=fy,
            status__in=LIVE_PLAN_STATUSES,
        ).exclude(school__isnull=True, cluster__isnull=True)
        verdicts = Counter(live.values_list("ssa_alignment", flat=True))
        by_type: dict[str, Counter] = defaultdict(Counter)
        for activity_type, alignment in live.values_list("activity_type", "ssa_alignment"):
            by_type[activity_type][alignment or "unjudged"] += 1
        total = sum(verdicts.values())
        informed = sum(verdicts.get(value, 0) for value in INFORMED)

        self.stdout.write(self.style.MIGRATE_HEADING(f"SSA-informed plans · FY {fy}"))
        self.stdout.write(f"Live school and cluster plans: {total}")
        if total:
            self.stdout.write(
                f"SSA informed: {informed} ({round(informed * 100 / total)}%)"
            )
        labels = dict(SsaAlignment.choices)
        for value, count in verdicts.most_common():
            self.stdout.write(f"  {labels.get(value, 'Not yet judged'):55} {count}")
        self.stdout.write("By activity type:")
        for activity_type, counts in sorted(by_type.items()):
            parts = ", ".join(
                f"{labels.get(value, 'unjudged')}: {count}"
                for value, count in counts.most_common()
            )
            self.stdout.write(f"  {activity_type:34} {parts}")

        schools = School.objects.filter(deleted_at__isnull=True)
        confirmed = SsaRecord.objects.filter(
            verification_status="confirmed", deleted_at__isnull=True
        )
        assessed = confirmed.values("school_id").distinct().count()
        recorded = SsaRecommendation.objects.values("school_id").distinct().count()
        states = Counter(SsaRecommendation.objects.values_list("state", flat=True))
        self.stdout.write(self.style.MIGRATE_HEADING("SSA recommendations"))
        self.stdout.write(
            f"Schools: {schools.count()} · with a confirmed SSA: {assessed} · "
            f"with recorded recommendations: {recorded}"
        )
        for state, count in states.most_common():
            self.stdout.write(f"  {state:12} {count}")
