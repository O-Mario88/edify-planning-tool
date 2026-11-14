"""Write targets_golden.json: the target engine's member cells as the existing
application computes them (PLTeamTargetsService._member over the roster's
own reads, as apps.hr.team_roster._target_bands asks it), for people and
years the development seed does not hold.

    DATABASE_URL=postgresql://localhost:5432/edify_gorn_test \\
    GOLDEN_OUT=/path/to/targets_golden.json \\
    python manage.py shell < platform/backend/internal/targets/testdata/golden.py

Only against a database whose name ends in "_test". It takes six CCEOs and
first lets the existing engine bring their ledgers up to date (refresh_many,
as any page that reads them does), then files, every id starting "gpt":
agreed reviews (one with a duplicate, an unmapped and a zero priority; an
older agreed review behind a newer one; a draft that does not count),
explicit monthly targets that win over a priority's annual figure, a target
profile, legacy monthly targets for a person with no agreement, validated
and unvalidated ledger rows, and approved, pending and unreadable leave. It
asks for each person's cells on several days of the year (its first and last
days, today, a day in Q2) and for the year before, writes the rows and the
answers to GOLDEN_OUT and deletes the rows.
internal/integration/targets_test.go files the same rows and compares.
"""

import json
import os
from datetime import date

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import connection
from django.utils import timezone as dj_timezone

from apps.accounts.models import (
    Leave,
    StaffProfile,
    StaffTargetProfile,
    attach_staff_profile_ids,
)
from apps.core import request_cache
from apps.core.fy import get_operational_fy
from apps.hr.models import PerformancePriority, PerformanceReview
from apps.hr.team_roster import _leave, _prime_leave_days
from apps.targets.fy_calendar import FinancialYearCalendarService as Cal
from apps.targets.ledger_sync import refresh_many
from apps.targets.models import (
    MonthlyPersonalTarget,
    TargetAchievementLedger,
    TargetArea,
)
from apps.targets.my_targets import (
    MyTargetQueryService,
    priority_target_areas_for_users,
)
from apps.targets.team_targets import PLTeamTargetsService

if not settings.DATABASES["default"]["NAME"].endswith("_test"):
    raise SystemExit("golden.py runs only against a _test database")

User = get_user_model()
#: Children first.
TABLES = (
    "hr_performance_priority",
    "hr_performance_review",
    "monthly_personal_target",
    "staff_target_profile",
    "target_achievement_ledger",
    "leave",
)


def clear():
    PerformancePriority.objects.filter(id__startswith="gpt").delete()
    PerformanceReview.objects.filter(id__startswith="gpt").delete()
    MonthlyPersonalTarget.objects.filter(id__startswith="gpt").delete()
    StaffTargetProfile.objects.filter(id__startswith="gpt").delete()
    TargetAchievementLedger.objects.filter(id__startswith="gpt").delete()
    Leave.objects.filter(id__startswith="gpt").delete()


def people():
    staff = list(
        StaffProfile.objects.filter(
            user__email__in=[f"cceo{n}@edify.org" for n in range(1, 7)]
        )
        .select_related("user")
        .order_by("user__email")
    )
    return staff


def file_rows(staff, fy):
    area = {a.key: a for a in TargetArea.objects.all()}
    p0, p1, p2, p3, p4, p5 = staff
    now = dj_timezone.now()
    due = date(int(fy), 9, 30)
    reviews = [
        PerformanceReview(
            id="gptr0",
            staff=p0,
            fy=fy,
            review_type="annual_priorities",
            due_date=due,
            stage="priorities_agreed",
        ),
        PerformanceReview(
            id="gptr1a",
            staff=p1,
            fy=fy,
            review_type="annual_priorities",
            due_date=due,
            stage="priorities_agreed",
        ),
        PerformanceReview(
            id="gptr1b",
            staff=p1,
            fy=fy,
            review_type="annual_priorities",
            due_date=due,
            stage="employee_reflection",
        ),
        PerformanceReview(
            id="gptr1c",
            staff=p1,
            fy=fy,
            review_type="annual_priorities",
            due_date=due,
            stage="priorities_draft",
        ),
        PerformanceReview(
            id="gptr4",
            staff=p4,
            fy=fy,
            review_type="annual_priorities",
            due_date=due,
            stage="priorities_agreed",
        ),
        PerformanceReview(
            id="gptr5",
            staff=p5,
            fy=fy,
            review_type="annual_priorities",
            due_date=due,
            stage="priorities_draft",
        ),
    ]
    PerformanceReview.objects.bulk_create(reviews)
    # The latest agreed review wins: gptr1b is the newer of p1's two.
    PerformanceReview.objects.filter(id="gptr1a").update(
        updated_at=now.replace(year=now.year - 1)
    )
    PerformanceReview.objects.filter(id="gptr1b").update(updated_at=now)
    PerformanceReview.objects.filter(id="gptr1c").update(
        updated_at=now.replace(year=now.year + 1)
    )

    def priority(key, review, seq, metric, target, weight, statement):
        return PerformancePriority(
            id=f"gptp{key}",
            review_id=review,
            sequence=seq,
            outcome_statement=statement,
            metric_key=metric,
            target_number=target,
            weight=weight,
        )

    PerformancePriority.objects.bulk_create(
        [
            priority("01", "gptr0", 1, "direct_visits", 120, 30, "Visit my schools"),
            priority("02", "gptr0", 2, "trainings", 30, 20, "Train clusters"),
            priority("03", "gptr0", 3, "ssa_coverage", 40, 25, "Collect SSAs"),
            priority(
                "04", "gptr0", 4, "direct_visits", 50, 10, "A second visits priority"
            ),
            priority("05", "gptr0", 5, "not_a_metric", 10, 10, "Unmapped"),
            priority("06", "gptr0", 6, "cluster_meetings", 0, 10, "No target"),
            priority("11", "gptr1a", 1, "direct_visits", 999, 50, "Old agreement"),
            priority("12", "gptr1b", 1, "cluster_meetings", 25, 40, "Meet clusters"),
            priority("13", "gptr1b", 2, "mscs", 7, 15, "Stories"),
            priority("41", "gptr4", 1, "mscs", 12, 10, "MSCS"),
            priority("42", "gptr4", 2, "direct_visits", 60, 30, "Visits"),
            priority("51", "gptr5", 1, "direct_visits", 80, 30, "Draft only"),
        ]
    )
    targets = []
    for m in (1, 2, 3):
        targets.append(
            MonthlyPersonalTarget(
                id=f"gptt0{m}",
                user_id=p0.user_id,
                fy=fy,
                month_of_fy=m,
                target=9,
                area=area["school_visits"],
            )
        )
    for m in range(1, 13):
        targets.append(
            MonthlyPersonalTarget(
                id=f"gptt2{m:02d}",
                user_id=p2.user_id,
                fy=fy,
                month_of_fy=m,
                target=2,
                area=area["cluster_meetings"],
            )
        )
    targets.append(
        MonthlyPersonalTarget(
            id="gptt5",
            user_id=p5.user_id,
            fy=fy,
            month_of_fy=1,
            target=0,
            area=area["mscs"],
        )
    )
    MonthlyPersonalTarget.objects.bulk_create(targets)
    StaffTargetProfile.objects.bulk_create(
        [
            StaffTargetProfile(
                id="gptf2",
                staff=p2,
                fy=fy,
                visits_target=24,
                trainings_target=6,
                ssa_target=10,
            )
        ]
    )

    def ledger(key, person, area_key, month, quantity, status="validated"):
        start, _ = Cal.month_range(fy, month)
        return TargetAchievementLedger(
            id=f"gptl{key}",
            user_id=person.user_id,
            area=area[area_key],
            source_type="activity",
            source_id=f"gpt-src-{key}",
            activity_date=start,
            fy=fy,
            credited_month=month,
            credited_quarter=Cal.quarter_of_month(month),
            quantity=quantity,
            validation_status=status,
        )

    TargetAchievementLedger.objects.bulk_create(
        [
            ledger("01", p0, "school_visits", 1, 10),
            ledger("02", p0, "school_visits", 2, 12),
            ledger("03", p0, "cluster_trainings", 2, 3),
            ledger("04", p0, "ssa_completed", 1, 2),
            ledger("05", p0, "school_visits", 1, 50, status="pending"),
            ledger("12", p1, "cluster_meetings", 1, 3),
            ledger("13", p1, "mscs", 2, 1),
            ledger("21", p2, "cluster_meetings", 1, 2),
            ledger("22", p2, "cluster_meetings", 2, 1),
            ledger("23", p2, "school_visits", 1, 5),
            ledger("41", p4, "school_visits", 1, 4),
        ]
    )

    def leave(key, person, status, start, end):
        return Leave(
            id=f"gptv{key}",
            staff=person,
            type="annual",
            start_date=start,
            end_date=end,
            days=1,
            status=status,
        )

    Leave.objects.bulk_create(
        [
            leave("1", p4, "approved", "2026-11-02", "2026-11-13"),
            leave("2", p4, "pending", "2026-11-16", "2026-11-20"),
            leave("3", p4, "approved", "not-a-day", "2026-11-20"),
            leave("4", p0, "approved", "2027-02-01T00:00:00", "2027-02-05"),
        ]
    )


def dump_rows():
    rows = {}
    with connection.cursor() as cursor:
        for table in TABLES:
            cursor.execute(
                f"SELECT row_to_json(t)::text FROM \"{table}\" t WHERE id LIKE 'gpt%%' ORDER BY id"  # noqa: S608  # nosec B608
            )
            rows[table] = [json.loads(r[0]) for r in cursor.fetchall()]
    return rows


def cells_for(staff, fy, today):
    """_target_bands' body without its refresh, returning every cell."""
    with request_cache.scoped():
        users = attach_staff_profile_ids([m.user for m in staff])
        _prime_leave_days(_leave([m.id for m in staff], today)["approved_rows"])
        month = Cal.month_of_fy_for(today, fy)
        is_current = month is not None
        month = month or 12
        m_start, m_end = Cal.month_range(fy, month)
        areas_by_user = priority_target_areas_for_users(users, fy)
        keys = sorted({a.key for u in users for a in areas_by_user.get(str(u.id), [])})
        explicit = MyTargetQueryService._explicit_targets(users, fy, keys)
        profiles = MyTargetQueryService._target_profiles(users, fy)
        ledger = MyTargetQueryService._validated_ledger(users, fy, keys)
        out = []
        for user in users:
            member = PLTeamTargetsService._member(
                user,
                areas_by_user.get(str(user.id), []),
                fy,
                month,
                today,
                m_start,
                m_end,
                is_current,
                prepared=(
                    explicit.get(user.id, {}),
                    profiles.get(user.staff_profile_id),
                    ledger.get(user.id, ()),
                ),
            )
            out.append(
                {
                    "user_id": user.id,
                    "staff_id": user.staff_profile_id,
                    "status": member["status"],
                    "tone": member["tone"],
                    "cells": [
                        {
                            k: c[k]
                            for k in (
                                "key",
                                "label",
                                "pct",
                                "display_pct",
                                "achieved",
                                "target",
                                "status",
                                "tone",
                            )
                        }
                        for c in member["matrix_cells"]
                    ],
                }
            )
        return out


def main():
    fy = get_operational_fy()
    staff = people()
    clear()
    try:
        # The existing engine rebuilds marked ledgers on every page that
        # reads them; doing it first leaves Go a current ledger to read.
        refresh_many(attach_staff_profile_ids([m.user for m in staff]), fy)
        refresh_many(
            attach_staff_profile_ids([m.user for m in staff]), str(int(fy) - 1)
        )
        file_rows(staff, fy)
        rows = dump_rows()
        today = dj_timezone.localdate()
        answers = []
        for when_fy, day in (
            (fy, today),
            (fy, date(int(fy) - 1, 10, 1)),
            (fy, date(int(fy), 3, 10)),
            (fy, date(int(fy), 9, 30)),
            (str(int(fy) - 1), today),
        ):
            answers.append(
                {
                    "fy": when_fy,
                    "today": day.isoformat(),
                    "people": cells_for(staff, when_fy, day),
                }
            )
    finally:
        clear()
    with open(os.environ["GOLDEN_OUT"], "w") as handle:
        json.dump(
            {
                "today": dj_timezone.localdate().isoformat(),
                "rows": rows,
                "answers": answers,
            },
            handle,
            ensure_ascii=False,
            indent=1,
            default=str,
        )
    print(f"{len(answers)} answers written")


main()
