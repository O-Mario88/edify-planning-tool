"""Write golden.json: Programme Rollout (/programme-rollout) on its Trainings
view as the existing feed reads it, for the first Programme Lead over
trainings the development seed does not hold, and the readers it refuses.

    DATABASE_URL=postgresql://localhost:5432/edify_gorn_test \\
    GOLDEN_OUT=/path/to/golden.json \\
    python manage.py shell < platform/backend/internal/programmerollout/testdata/golden.py

Only against a database whose name ends in "_test". It files, every id
starting "gpr", copies of one stored visit as the team's trainings: an
in-school course delivered at an officer's school, a partner's cluster
training verified with one school's attendance confirmed, one held and in
review with no intervention, one scheduled in the next days, a partner's
dated cluster training, one planned months ahead, one cancelled, and one
delivered last year. It asks the page as the Lead (each year and the view
named) and as the officer and the Accountant it refuses, writes the rows and
the answers, and deletes the rows.
"""

import json
import os
from datetime import timedelta

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import connection, transaction
from django.utils import timezone as dj_timezone

from apps.mobile_feed.views import read_page

if not settings.DATABASES["default"]["NAME"].endswith("_test"):
    raise SystemExit("golden.py runs only against a _test database")

User = get_user_model()
PATH = "/programme-rollout"
#: The second and third Programme Leads' staff profiles, chosen by the Admin
#: and Impact Assessment.
PL2 = "cmw9p7b6a00e4s8ekhefr"
PL3 = "cmw9p7bf200eymgekhexn"
NOW = dj_timezone.now()
TODAY = dj_timezone.localdate()
TABLES = (
    ("activity", "id"),
    ("cluster_activity_attendance", "activity_id"),
    ("ssa_record", "id"),
    ("ssa_score", "ssa_record_id"),
    ("partner_assignment", "id"),
    ("staff_school_assignment", "id"),
    ("cce_regional_engagement", "id"),
    ("partner_engagement", "id"),
)


def clear():
    with connection.cursor() as cursor:
        for table, column in reversed(TABLES):
            cursor.execute(f"DELETE FROM {table} WHERE {column} LIKE 'gpr%%'")


def one(cursor, sql, args=()):
    cursor.execute(sql, args)
    row = cursor.fetchone()
    return row[0] if row else None


def file_rows():
    with connection.cursor() as cursor:
        officer = one(
            cursor,
            'SELECT sp.id FROM staff_profile sp JOIN "user" u ON u.id = sp.user_id '
            "WHERE u.email = 'cceo@edify.org'",
        )
        cursor.execute(
            "SELECT s.id, s.cluster_id FROM staff_school_assignment a JOIN school s ON s.id = a.school_id "
            "WHERE a.staff_id = %s AND s.deleted_at IS NULL AND s.cluster_id IS NOT NULL ORDER BY s.id LIMIT 4",
            [officer],
        )
        schools = cursor.fetchall()
        course = one(
            cursor,
            "SELECT id FROM activity_catalogue_item WHERE is_training_course AND status = 'active' ORDER BY id LIMIT 1",
        )
        partner = one(
            cursor,
            "SELECT id FROM partner WHERE deleted_at IS NULL ORDER BY id LIMIT 1",
        )
        base = one(
            cursor,
            "SELECT id FROM activity WHERE activity_type = 'school_visit' AND deleted_at IS NULL ORDER BY id LIMIT 1",
        )
        stamp = NOW.isoformat()
        n = 0

        def work(**fields):
            nonlocal n
            n += 1
            overrides = {
                "id": f"gpr{n:02d}",
                "fy": "2027",
                "quarter": "Q1",
                "planned_month": TODAY.month,
                "delivery_type": "staff",
                "responsible_staff_id": officer,
                "monitored_by_staff_id": None,
                "assigned_partner_id": None,
                "school_id": schools[0][0],
                "cluster_id": None,
                "focus_intervention": "christlike_behaviour",
                "catalogue_item_id": None,
                "training_course_id": None,
                "activity_name_snapshot": "",
                "teachers_attended": 0,
                "leaders_attended": 0,
                "attended_school_ids": [],
                "paired_school_visit_id": None,
                "daily_visit_batch_id": None,
                "created_at": stamp,
                "updated_at": stamp,
                **fields,
            }
            cursor.execute(
                'INSERT INTO "activity" SELECT (json_populate_record(NULL::"activity", '
                '(row_to_json(t)::jsonb || %s::jsonb)::json)).* FROM "activity" t WHERE id = %s',
                [json.dumps(overrides, default=str), base],
            )
            return overrides["id"]

        def on(days):
            return (TODAY + timedelta(days=days)).isoformat()

        work(
            activity_type="in_school_training",
            status="completed",
            planned_date=on(-12),
            training_course_id=course,
            teachers_attended=6,
            leaders_attended=2,
        )
        cluster = work(
            activity_type="cluster_training",
            status="ia_verified",
            planned_date=on(-20),
            delivery_type="partner",
            assigned_partner_id=partner,
            responsible_staff_id=None,
            monitored_by_staff_id=officer,
            school_id=None,
            cluster_id=schools[1][1],
            focus_intervention="leadership",
            teachers_attended=14,
            leaders_attended=4,
            attended_school_ids=[schools[1][0]],
        )
        work(
            activity_type="training",
            status="submitted_to_pl",
            planned_date=on(-3),
            focus_intervention="",
            activity_name_snapshot="Classroom discipline refresher",
            school_id=schools[2][0],
        )
        work(
            activity_type="in_school_training",
            status="scheduled",
            planned_date=on(5),
            training_course_id=course,
            school_id=schools[3][0],
        )
        work(
            activity_type="cluster_training",
            status="partner_scheduled",
            planned_date=on(10),
            delivery_type="partner",
            assigned_partner_id=partner,
            responsible_staff_id=None,
            monitored_by_staff_id=officer,
            school_id=None,
            cluster_id=schools[1][1],
            focus_intervention="exposure_to_word_of_god",
        )
        work(activity_type="training", status="planned", planned_date=on(70))
        work(activity_type="training", status="cancelled", planned_date=on(2))
        work(
            activity_type="in_school_training",
            status="completed",
            planned_date=on(-300),
            fy="2026",
            teachers_attended=3,
            school_id=schools[2][0],
        )
        cursor.execute(
            "INSERT INTO cluster_activity_attendance (created_at, updated_at, activity_id, school_id, "
            "invited, attended, is_guest, recorded_by) VALUES (%s, %s, %s, %s, true, true, false, '')",
            [stamp, stamp, cluster, schools[0][0]],
        )
        file_ssa(cursor, work, on, officer, partner, stamp)
        file_spiritual(cursor, work, on, officer, partner, stamp)
        file_observations(cursor, on, partner, stamp)


def file_ssa(cursor, work, on, officer, partner, stamp):
    """The Self-Assessments view's facts over schools with no confirmed SSA
    this year, each cluster's schools apart: records pending, flagged, deleted
    and newly confirmed with scores; collections at a school scheduled, held
    and cancelled; a cluster collection with nobody recorded and one with an
    invitation and a recorded school; a partner hand-over at a school, one at
    a cluster by its catalogue item, and one already scheduled."""
    cursor.execute(
        "SELECT s.id, s.cluster_id FROM staff_school_assignment a JOIN school s ON s.id = a.school_id "
        "WHERE a.staff_id = %s AND s.deleted_at IS NULL AND s.cluster_id IS NOT NULL "
        "AND s.operational_status IN ('active', 'reopened') AND NOT EXISTS (SELECT 1 FROM ssa_record r "
        "WHERE r.school_id = s.id AND r.fy = '2027' AND r.deleted_at IS NULL) ORDER BY s.cluster_id, s.id",
        [officer],
    )
    by_cluster = {}
    for school_id, cluster_id in cursor.fetchall():
        by_cluster.setdefault(cluster_id, []).append(school_id)
    clusters = sorted(by_cluster)
    # Single-school facts come from clusters the cluster-wide facts leave alone.
    single = [sid for c in clusters[3:] for sid in by_cluster[c]]
    invited = by_cluster[clusters[1]]
    confirmed_school = one_confirmed(cursor, officer)
    base_record = one(
        cursor,
        "SELECT id FROM ssa_record WHERE verification_status = 'confirmed' AND deleted_at IS NULL ORDER BY id LIMIT 1",
    )
    n = 0

    def record(school_id, **fields):
        nonlocal n
        n += 1
        overrides = {
            "id": f"gprs{n:02d}",
            "school_id": school_id,
            "fy": "2027",
            "quarter": "Q1",
            "date_of_ssa": on(-15) + "T09:00:00+00:00",
            "verification_status": "pending",
            "source_activity_id": None,
            "salesforce_id": None,
            "deleted_at": None,
            "created_at": stamp,
            "updated_at": stamp,
            **fields,
        }
        cursor.execute(
            'INSERT INTO "ssa_record" SELECT (json_populate_record(NULL::"ssa_record", '
            '(row_to_json(t)::jsonb || %s::jsonb)::json)).* FROM "ssa_record" t WHERE id = %s',
            [json.dumps(overrides, default=str), base_record],
        )
        return overrides["id"]

    record(single[0])
    record(single[1], verification_status="flagged")
    record(single[2], deleted_at=stamp)
    scored = record(single[3], verification_status="confirmed", average_score=7.25)
    for index, (intervention, score) in enumerate(
        (
            ("christlike_behaviour", 8.25),
            ("exposure_to_word_of_god", 6.75),
            ("financial_health", 4.0),
            ("leadership", 9.5),
        )
    ):
        cursor.execute(
            "INSERT INTO ssa_score (id, created_at, updated_at, ssa_record_id, intervention, score) "
            "VALUES (%s, %s, %s, %s, %s, %s)",
            [f"{scored}x{index}", stamp, stamp, scored, intervention, score],
        )

    collection = {"fy": "2027", "focus_intervention": "", "school_id": None}
    work(
        activity_type="school_visit_ssa_collection",
        status="scheduled",
        planned_date=on(6),
        **{**collection, "school_id": single[4]},
    )
    work(
        activity_type="baseline_ssa_visit",
        status="completed",
        planned_date=on(-9),
        **{**collection, "school_id": single[5]},
    )
    work(
        activity_type="ssa_activity",
        status="cancelled",
        planned_date=on(3),
        **{**collection, "school_id": single[6]},
    )
    work(
        activity_type="school_visit_ssa_collection",
        status="scheduled",
        planned_date=on(4),
        **{**collection, "school_id": confirmed_school},
    )
    work(
        activity_type="cluster_training_ssa_collection",
        status="partner_scheduled",
        planned_date=on(8),
        delivery_type="partner",
        assigned_partner_id=partner,
        responsible_staff_id=None,
        monitored_by_staff_id=None,
        **{**collection, "cluster_id": clusters[0]},
    )
    reviewed = work(
        activity_type="cluster_meeting_ssa_review",
        status="evidence_uploaded",
        planned_date=on(-4),
        responsible_staff_id=None,
        monitored_by_staff_id=None,
        attended_school_ids=[invited[1]],
        **{**collection, "cluster_id": clusters[1]},
    )
    cursor.execute(
        "INSERT INTO cluster_activity_attendance (created_at, updated_at, activity_id, school_id, "
        "invited, attended, is_guest, recorded_by) VALUES (%s, %s, %s, %s, true, false, false, '')",
        [stamp, stamp, reviewed, invited[0]],
    )

    base_assignment = one(
        cursor, "SELECT id FROM partner_assignment ORDER BY id LIMIT 1"
    )
    workflow_item = one(
        cursor,
        "SELECT id FROM activity_catalogue_item WHERE workflow_kind = 'school_visit_ssa_collection' ORDER BY id LIMIT 1",
    )
    m = 0

    def assignment(**fields):
        nonlocal m
        m += 1
        overrides = {
            "id": f"gpra{m:02d}",
            "status": "assigned",
            "partner_id": partner,
            "school_id": None,
            "cluster_id": None,
            "catalogue_item_id": None,
            "expected_activity_type": "",
            "scheduled_activity_id": None,
            "source_activity_id": None,
            "source_ssa_id": None,
            "replaces_assignment_id": None,
            "support_type": None,
            "visit_number": None,
            "training_number": None,
            "purpose_of_visit": "",
            "created_at": stamp,
            "updated_at": stamp,
            **fields,
        }
        cursor.execute(
            'INSERT INTO "partner_assignment" SELECT (json_populate_record(NULL::"partner_assignment", '
            '(row_to_json(t)::jsonb || %s::jsonb)::json)).* FROM "partner_assignment" t WHERE id = %s',
            [json.dumps(overrides, default=str), base_assignment],
        )

    assignment(school_id=single[7], expected_activity_type="partner_ssa_collection")
    assignment(
        cluster_id=clusters[2],
        status="pending_scheduling",
        catalogue_item_id=workflow_item,
    )
    assignment(
        school_id=single[8],
        status="partner_scheduled",
        expected_activity_type="partner_ssa_collection",
    )
    assignment(
        school_id=single[9],
        expected_activity_type="partner_ssa_collection",
        created_at="2025-06-01T08:00:00+00:00",
    )


def file_spiritual(cursor, work, on, officer, partner, stamp):
    """The Spiritual Formation view's facts: two schools outside any cluster
    whose only confirmed SSA is last year's, one weak in both of the pair and
    answered in one (its focus), one weak in the Word of God alone and
    answered by a secondary focus, both shared with an officer of the second
    Programme Lead; and the team's Christian Transformation course delivered,
    a CC-SEL session a partner has dated, a camp held in review and a
    cancelled one."""
    from apps.hr.team_roster import team_members

    cursor.execute(
        "SELECT r.school_id, string_agg(x.intervention, ',' ORDER BY x.score, x.intervention) "
        "FROM ssa_record r JOIN ssa_score x ON x.ssa_record_id = r.id JOIN school s ON s.id = r.school_id "
        "JOIN staff_school_assignment a ON a.school_id = s.id AND a.staff_id = %s "
        "WHERE r.fy = '2026' AND r.verification_status = 'confirmed' AND r.deleted_at IS NULL "
        "AND s.cluster_id IS NULL AND s.deleted_at IS NULL AND s.operational_status IN ('active', 'reopened') "
        "AND NOT EXISTS (SELECT 1 FROM ssa_record o WHERE o.school_id = s.id AND o.fy = '2027') "
        "GROUP BY r.school_id ORDER BY r.school_id",
        [officer],
    )
    both = alone = strong = None
    for school_id, order in cursor.fetchall():
        weakest = order.split(",")[:3]
        pair = {"christlike_behaviour", "exposure_to_word_of_god"} & set(weakest)
        if len(pair) == 2 and both is None:
            both = school_id
        elif pair == {"exposure_to_word_of_god"} and alone is None:
            alone = school_id
        elif not pair and strong is None:
            strong = school_id
    lead = User.objects.get(email="pl2@edify.org")
    colleague = sorted(team_members(lead), key=lambda p: p.id)[0].id
    for index, (school_id, staff_id) in enumerate(
        ((both, colleague), (alone, colleague), (strong, lead.staff_profile.id)),
        start=1,
    ):
        cursor.execute(
            "INSERT INTO staff_school_assignment (id, created_at, updated_at, school_id, staff_id) "
            "VALUES (%s, %s, %s, %s, %s)",
            [f"gprt{index:02d}", stamp, stamp, school_id, staff_id],
        )
    work(
        activity_type="school_visit",
        status="scheduled",
        planned_date=on(12),
        school_id=both,
        focus_intervention="christlike_behaviour",
        activity_name_snapshot="Character follow-up visit",
    )
    work(
        activity_type="school_visit",
        status="planned",
        planned_date=None,
        school_id=alone,
        focus_intervention="leadership",
        secondary_focus_interventions=["exposure_to_word_of_god"],
    )
    work(
        activity_type="school_visit",
        status="cancelled",
        planned_date=on(1),
        school_id=both,
        focus_intervention="exposure_to_word_of_god",
    )
    christian = "cmw9p6zjg00u2wieihg9o"
    work(
        activity_type="in_school_training",
        status="completed",
        planned_date=on(-6),
        training_course_id=christian,
        teachers_attended=5,
    )
    work(
        activity_type="cluster_training",
        status="partner_scheduled",
        planned_date=on(9),
        catalogue_item_id="cmw9p6zui00zapceihg6m",
        delivery_type="partner",
        assigned_partner_id=partner,
        responsible_staff_id=None,
        monitored_by_staff_id=officer,
        school_id=None,
        cluster_id=one(
            cursor,
            "SELECT cluster_id FROM school WHERE cluster_id IS NOT NULL ORDER BY id LIMIT 1",
        ),
    )
    work(
        activity_type="training",
        status="submitted_to_pl",
        planned_date=on(-2),
        catalogue_item_id="cmw9p6zst00z4rbeihgve",
    )
    work(
        activity_type="training",
        status="cancelled",
        planned_date=on(-1),
        catalogue_item_id="cmw9p6zt500ttxweihgpq",
    )


PL1 = "cmw9p7axf00zhz7ekherr"
CHRISTIAN_COURSE = "cmw9p6zjg00u2wieihg9o"
CC_SEL = "cmw9p6zui00zapceihg6m"


def file_observations(cursor, on, partner, stamp):
    """The Regional Lead's observations: shared with the first lead, of an
    officer's course (strengthen, open, answered by two partner follow-ups),
    a partner's cluster training (replace, answered), the Christian
    Transformation course (continue), a workshop with no training named
    (strengthen, open) and the partner's CC-SEL session (economize, not
    rated); one unshared, one shared with the second lead only and one of
    last year."""
    author = one(
        cursor, "SELECT id FROM \"user\" WHERE email = 'regional-lead@edify.org'"
    )
    lead_user = one(cursor, "SELECT user_id FROM staff_profile WHERE id = %s", [PL1])

    def activity(where):
        return one(
            cursor,
            f"SELECT id FROM activity WHERE id LIKE 'gpr%%' AND {where} ORDER BY id LIMIT 1",
        )

    n = 0

    def observe(
        held, activity_id=None, recommendation="continue", ratings=(None,) * 5, **fields
    ):
        nonlocal n
        n += 1
        row = {
            "id": f"gpro{n:02d}",
            "created_at": f"2026-11-01T08:{n:02d}:00+00:00",
            "updated_at": stamp,
            "author_id": author,
            "kind": "training_observation",
            "held_on": on(held),
            "fy": "2027",
            "country": "Uganda",
            "program_lead_ids": [PL1],
            "subject": f"Observation {n}",
            "notes": "",
            "agreed_actions": "",
            "recommendation": recommendation,
            "feedback": "",
            "feedback_shared_at": stamp,
            "acknowledged_at": None,
            "lead_response": "",
            "activity_id": activity_id,
            "rating_biblical_integration": ratings[0],
            "rating_need_alignment": ratings[1],
            "rating_facilitation": ratings[2],
            "rating_participation": ratings[3],
            "rating_application": ratings[4],
            **fields,
        }
        cursor.execute(
            'INSERT INTO "cce_regional_engagement" SELECT * FROM json_populate_record(NULL::"cce_regional_engagement", %s::json)',
            [json.dumps(row, default=str)],
        )
        return row["id"]

    course = activity(
        "activity_type = 'in_school_training' AND training_course_id IS NOT NULL AND training_course_id <> %s"
        % repr(CHRISTIAN_COURSE)
    )
    strengthen = observe(-10, course, "strengthen", (3, 2, 3, 4, None))
    replaced = observe(
        -18,
        activity("activity_type = 'cluster_training' AND status = 'ia_verified'"),
        "replace",
        (1, 2, 2, 1, 2),
        acknowledged_at=stamp,
    )
    observe(
        -5,
        activity(f"training_course_id = '{CHRISTIAN_COURSE}'"),
        "continue",
        (4, 4, 3, 4, 4),
    )
    observe(
        -5,
        None,
        "strengthen",
        (2, None, None, None, None),
        subject="District leaders' workshop",
    )
    observe(-1, activity(f"catalogue_item_id = '{CC_SEL}'"), "economize")
    observe(-3, course, "strengthen", (1, 1, 1, 1, 1), feedback_shared_at=None)
    observe(
        -3,
        course,
        "replace",
        (2, 2, 2, 2, 2),
        program_lead_ids=["cmw9p7b6a00e4s8ekhefr"],
    )
    observe(-300, course, "strengthen", (3, 3, 3, 3, 3), fy="2026")

    for index, (source, held, author_id) in enumerate(
        (
            (strengthen, on(-2), lead_user),
            (strengthen, on(-6), lead_user),
            (replaced, on(-1), author),
        ),
        start=1,
    ):
        cursor.execute(
            "INSERT INTO partner_engagement (created_at, updated_at, id, author_id, author_role, kind, held_on, fy, country, "
            "subject, notes, agreed_improvements, follow_up_note, partner_id, source_engagement_id) "
            "VALUES (%s, %s, %s, %s, 'Program Lead', 'quality_follow_up', %s, '2027', 'Uganda', '', '', '', '', %s, %s)",
            [stamp, stamp, f"gprp{index:02d}", author_id, held, partner, source],
        )


def one_confirmed(cursor, officer):
    return one(
        cursor,
        "SELECT r.school_id FROM ssa_record r JOIN staff_school_assignment a ON a.school_id = r.school_id "
        "WHERE a.staff_id = %s AND r.fy = '2027' AND r.verification_status = 'confirmed' AND r.deleted_at IS NULL "
        "ORDER BY r.school_id LIMIT 1",
        [officer],
    )


def dump_rows():
    out = {}
    with connection.cursor() as cursor:
        for table, column in TABLES:
            cursor.execute(
                f"SELECT row_to_json(t)::text FROM {table} t WHERE {column} LIKE 'gpr%%' ORDER BY ctid"
            )
            out[table] = [json.loads(r[0]) for r in cursor.fetchall()]
    return out


clear()
answers = []
try:
    file_rows()
    rows = dump_rows()
    for email, query in (
        ("pl1@edify.org", {}),
        ("pl1@edify.org", {"view": "trainings"}),
        ("pl1@edify.org", {"view": " Trainings "}),
        ("pl1@edify.org", {"fy": "2026"}),
        ("pl1@edify.org", {"fy": "bogus"}),
        ("pl1@edify.org", {"view": "ssa"}),
        ("pl1@edify.org", {"view": "SSA", "fy": "2026"}),
        ("pl1@edify.org", {"view": "ssa", "fy": "2025"}),
        ("pl1@edify.org", {"view": "spiritual"}),
        ("pl1@edify.org", {"view": " Spiritual "}),
        ("pl1@edify.org", {"view": "spiritual", "weak_page": "2"}),
        ("pl1@edify.org", {"view": "spiritual", "weak_page": "99"}),
        ("pl1@edify.org", {"view": "spiritual", "weak_page": "x"}),
        ("pl2@edify.org", {"view": "spiritual"}),
        ("pl2@edify.org", {"view": "spiritual", "fy": "2026"}),
        ("pl2@edify.org", {"view": "spiritual", "fy": "2025"}),
        ("pl2@edify.org", {"view": "spiritual", "fy": "2027", "weak_page": "3"}),
        ("pl2@edify.org", {}),
        ("pl2@edify.org", {"view": "ssa"}),
        ("admin@edify.org", {}),
        ("admin@edify.org", {"view": "ssa"}),
        ("admin@edify.org", {"view": "spiritual"}),
        ("admin@edify.org", {"lead": PL2}),
        ("admin@edify.org", {"lead": PL2, "view": "spiritual"}),
        ("admin@edify.org", {"lead": PL2, "view": "ssa", "fy": "2026"}),
        ("ia@edify.org", {"lead": "bogus", "view": "ssa"}),
        ("ia@edify.org", {"lead": f" {PL3} "}),
        ("cceo@edify.org", {}),
        ("accountant@edify.org", {}),
    ):
        with transaction.atomic():
            status, body = read_page(User.objects.get(email=email), PATH, query)
            transaction.set_rollback(True)
        answers.append(
            {
                "email": email,
                "path": PATH,
                "query": query,
                "status": status,
                "body": body,
            }
        )
finally:
    clear()

with open(os.environ["GOLDEN_OUT"], "w") as handle:
    json.dump(
        {"written": NOW.isoformat(), "rows": rows, "answers": answers},
        handle,
        ensure_ascii=False,
        indent=1,
        default=str,
    )
print(f"{len(answers)} pages asked")
