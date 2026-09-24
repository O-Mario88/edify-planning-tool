"""Old-against-new oracle for the Outcomes view's speed-up (2026-09-24).

`improvement_frame`, `_latest_confirmed_records` and `portfolio_change` were
rewritten for speed only: DISTINCT ON and an array parameter in SQL, the UTC
assessment date read in SQL, and no DataFrame round trip on the Outcomes view.
Their implementations before the change are copied below verbatim as frozen
references, and every test asserts the new code returns exactly what the
reference does — values, types and order — on a world built to reach the edge
cases: several records per school per FY, same-date ties, unconfirmed and
soft-deleted records, missing average scores, readings that straddle UTC
midnight, schools with no district or no cluster, several FYs, published
rules (country and deployment thresholds, maintain-strong) and the IA,
Country Director, Programme Lead, CCEO, Admin and RVP scopes.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
from datetime import timezone as dt_timezone
from decimal import Decimal
from statistics import median

import pandas as pd
from django.test import TestCase

from apps.accounts.models import (
    StaffProfile,
    StaffSchoolAssignment,
    StaffSupervisorAssignment,
    User,
)
from apps.activity_catalogue.models import (
    ActivityCatalogueItem,
    ActivityInterventionMapping,
    ExpectedDirection,
    MappingMode,
    MappingStatus,
)
from apps.analytics import ia_workflow, impact_engine
from apps.analytics.ia_workflow import (
    INTERVENTION_LABELS,
    PORTFOLIO_LIMITATION,
    _change_row,
    _outcome_area_groups,
    _share,
    portfolio_tiles,
)
from apps.clusters.models import Cluster
from apps.core.enums import SsaIntervention, VerificationStatus
from apps.core.rbac import EdifyRole
from apps.core.scoping import resolve_user_scope, scoped_school_queryset
from apps.geography.models import District, Region
from apps.impact.models import DefinitionStatus, OutcomeArea, OutcomeAreaDomain
from apps.schools.models import School
from apps.ssa.models import SsaRecord, SsaScore

ALL_INTERVENTIONS = [i.value for i in SsaIntervention]
CB = SsaIntervention.CHRISTLIKE_BEHAVIOUR.value
WOG = SsaIntervention.EXPOSURE_TO_WORD_OF_GOD.value
LEAD = SsaIntervention.LEADERSHIP.value
FIN = SsaIntervention.FINANCIAL_HEALTH.value
FYS = ("2024", "2025", "2026", "2027")


# ── Frozen references: the implementations at ee3fe7a, verbatim ─────────────


def _reference_latest_confirmed_records(
    school_ids: list[str], fy: str
) -> dict[str, dict]:
    """Latest confirmed SSA record per school for one FY (upload enforces one
    per FY; newest-first dedupe keeps this robust against legacy duplicates)."""
    rows = (
        SsaRecord.objects.filter(
            school_id__in=school_ids,
            fy=fy,
            deleted_at__isnull=True,
            verification_status=VerificationStatus.CONFIRMED.value,
        )
        .values("id", "school_id", "date_of_ssa")
        .order_by("school_id", "-date_of_ssa", "-created_at")
    )
    latest: dict[str, dict] = {}
    for row in rows:
        latest.setdefault(row["school_id"], row)
    return latest


def _reference_improvement_frame(school_ids: list[str], fy: str) -> pd.DataFrame:
    """One row per (school, intervention) with both cycles present:
    columns school_id, intervention, prev_score, curr_score, delta,
    window_start, window_end (assessment dates bounding the exposure)."""
    prev_fy = str(int(fy) - 1)
    curr = _reference_latest_confirmed_records(school_ids, fy)
    prev = _reference_latest_confirmed_records(list(curr.keys()), prev_fy)
    paired_schools = [sid for sid in curr if sid in prev]
    if not paired_schools:
        return pd.DataFrame(
            columns=[
                "school_id",
                "intervention",
                "prev_score",
                "curr_score",
                "delta",
                "window_start",
                "window_end",
            ]
        )

    record_ids = [curr[s]["id"] for s in paired_schools] + [
        prev[s]["id"] for s in paired_schools
    ]
    scores: dict[str, dict[str, float]] = defaultdict(dict)
    for row in SsaScore.objects.filter(ssa_record_id__in=record_ids).values(
        "ssa_record_id", "intervention", "score"
    ):
        scores[row["ssa_record_id"]][row["intervention"]] = float(row["score"])

    rows = []
    for sid in paired_schools:
        prev_map = scores.get(prev[sid]["id"], {})
        curr_map = scores.get(curr[sid]["id"], {})
        for intervention in ALL_INTERVENTIONS:
            if intervention not in prev_map or intervention not in curr_map:
                continue
            rows.append(
                {
                    "school_id": sid,
                    "intervention": intervention,
                    "prev_score": prev_map[intervention],
                    "curr_score": curr_map[intervention],
                    "delta": curr_map[intervention] - prev_map[intervention],
                    "window_start": prev[sid]["date_of_ssa"].date(),
                    "window_end": curr[sid]["date_of_ssa"].date(),
                }
            )
    return pd.DataFrame(rows)


def _reference_portfolio_change(user, *, fy: str) -> dict:
    """Paired confirmed SSAs across every school in the reader's scope, FY-1
    against FY, judged by apps.ssa.change_rules (seven queries at most)."""
    from apps.analytics.evidence_strength import grade
    from apps.ssa import change_rules

    scope = resolve_user_scope(user)
    schools = scoped_school_queryset(scope)
    prev_fy = str(int(fy) - 1)
    base = {
        "fy": fy,
        "prev_fy": prev_fy,
        "schools_in_scope": 0,
        "measured": 0,
        "improved": 0,
        "declined": 0,
        "no_change": 0,
        "improved_pct": None,
        "declined_pct": None,
        "median_interval_days": None,
        "rows": [],
        "rule_label": change_rules.FALLBACK_LABEL,
        "rule_sentence": change_rules.RULE_SENTENCE,
        "grade": grade(0),
        "limitation": PORTFOLIO_LIMITATION,
    }
    if schools is None or scope.can_view_summary_only:
        return base
    countries = dict(schools.values_list("id", "region__country"))
    base["schools_in_scope"] = len(countries)
    if not countries:
        return base
    frame = _reference_improvement_frame(list(countries), fy)
    book = change_rules.RuleBook()
    base["rule_label"] = change_rules.rule_label_for(book)

    def country_for(school_id):
        return countries.get(school_id) or ""

    pairs = (
        change_rules.classify_pairs(
            frame.to_dict("records"), book=book, country_for=country_for
        )
        if not frame.empty
        else []
    )
    groups = _outcome_area_groups()
    if not pairs:
        base["rows"] = [
            {"name": g["name"], "is_area": True, "n": 0, "domains": g["domains"]}
            for g in groups
        ]
        return base
    verdicts = change_rules.school_verdicts(pairs, book=book, country_for=country_for)
    by_class = Counter(v["classification"] for v in verdicts.values())
    intervals = {
        p["school_id"]: (p["window_end"] - p["window_start"]).days
        for p in pairs
        if p.get("window_start") and p.get("window_end")
    }
    measured = len(verdicts)
    base.update(
        measured=measured,
        improved=by_class[change_rules.IMPROVED],
        declined=by_class[change_rules.DECLINED],
        no_change=by_class[change_rules.NO_CHANGE],
        improved_pct=_share(by_class[change_rules.IMPROVED], measured),
        declined_pct=_share(by_class[change_rules.DECLINED], measured),
        median_interval_days=round(median(intervals.values())) if intervals else None,
        grade=grade(
            measured,
            confirmed_share=1.0,
            missing_share=1 - measured / len(countries),
        ),
    )

    rows = []
    for group in groups:
        area_pairs = [p for p in pairs if p["intervention"] in group["domains"]]
        area_verdicts = change_rules.school_verdicts(
            area_pairs, book=book, country_for=country_for
        )
        rows.append(
            {
                **_change_row(
                    group["name"],
                    area_pairs,
                    area_verdicts,
                    schools_in_scope=len(countries),
                    is_area=True,
                ),
                "domains": group["domains"],
            }
        )
        for code in group["domains"]:
            domain_pairs = [p for p in area_pairs if p["intervention"] == code]
            rows.append(
                _change_row(
                    INTERVENTION_LABELS.get(code, code),
                    domain_pairs,
                    {},
                    schools_in_scope=len(countries),
                    is_area=False,
                )
            )
    base["rows"] = rows
    return base


# ── Helpers ─────────────────────────────────────────────────────────────────


def _typed(value):
    """A value with the exact type of everything in it, so 1 never equals 1.0
    and a date never equals a datetime by accident; dict order counts."""
    if isinstance(value, dict):
        return ("dict", [(key, _typed(item)) for key, item in value.items()])
    if isinstance(value, (list, tuple)):
        return (type(value).__name__, [_typed(item) for item in value])
    if isinstance(value, float) and value != value:
        return ("float", "nan")
    return (type(value).__name__, value)


def _at(year, month, day, hour=9, minute=0):
    return datetime(year, month, day, hour, minute, tzinfo=dt_timezone.utc)


def _user(email, role, country="Uganda"):
    user = User.objects.create_user(
        email=email,
        name=email.split("@")[0],
        roles=[role],
        active_role=role,
        password="x",
        is_active=True,
    )
    StaffProfile.objects.create(user=user, title=role, country=country)
    return User.objects.select_related("staff_profile").get(pk=user.pk)


def _rule(code, intervention, *, threshold=None, direction=None, country=""):
    item = ActivityCatalogueItem.objects.create(
        stable_code=code,
        source_name=code,
        display_name=code.replace("_", " ").title(),
        activity_type="training",
        status="active",
        requires_school=True,
        costing_profile="IN_SCHOOL_TRAINING",
        evidence_profile="TRAINING_ATTENDANCE",
        salesforce_record_type="TRAINING",
    )
    return ActivityInterventionMapping.objects.create(
        catalogue_item=item,
        intervention=intervention,
        mapping_mode=MappingMode.FIXED,
        status=MappingStatus.PUBLISHED,
        active=True,
        min_meaningful_change=threshold,
        expected_direction=direction or ExpectedDirection.IMPROVE,
        country=country,
        effective_from=date(2025, 10, 1),
    )


def _area(code, name, domains, status=DefinitionStatus.APPROVED):
    area = OutcomeArea.objects.create(
        code=code, name=name, definition=name, status=status, author_id="oracle"
    )
    for intervention in domains:
        OutcomeAreaDomain.objects.create(area=area, intervention=intervention)
    return area


def _scores(seed: int, shift: float) -> dict[str, float]:
    """Deterministic, uneven scores: every classification is reached, and the
    deltas are not exactly representable in binary."""
    return {
        code: round(
            min(10.0, max(0.0, 2.0 + ((seed * 3 + j * 5) % 9) * 0.75 + shift * j)), 2
        )
        for j, code in enumerate(ALL_INTERVENTIONS)
    }


class OracleWorld(TestCase):
    @classmethod
    def setUpTestData(cls):
        central = Region.objects.create(name="Oracle Central", country="Uganda")
        west = Region.objects.create(name="Oracle West", country="Uganda")
        coast = Region.objects.create(name="Oracle Coast", country="Kenya")
        d1 = District.objects.create(name="Oracle Wakiso", region=central)
        d2 = District.objects.create(name="Oracle Kasese", region=west)
        kd = District.objects.create(name="Oracle Mombasa", region=coast)
        cluster = Cluster.objects.create(
            name="Oracle Cluster", region=central, district=d1
        )

        def school(code, region=None, district=None, *, in_cluster=False):
            row = School.objects.create(
                name=f"Oracle {code}", school_id=code, region=region, district=district
            )
            if in_cluster:
                School.objects.filter(pk=row.pk).update(cluster_id=cluster.id)
            return row

        def ssa(
            row, fy, on, scores, *, status="confirmed", deleted=False, average=True
        ):
            record = SsaRecord.objects.create(
                school=row,
                fy=fy,
                quarter="Q2",
                date_of_ssa=on,
                verification_status=status,
                average_score=(
                    round(sum(scores.values()) / len(scores), 2)
                    if average and scores
                    else None
                ),
                deleted_at=on if deleted else None,
                uploaded_by="oracle",
            )
            SsaScore.objects.bulk_create(
                SsaScore(ssa_record=record, intervention=code, score=value)
                for code, value in scores.items()
            )
            return record

        cls.regular = []
        for i in range(20):
            row = school(
                f"ORC-{i:02d}",
                central if i % 2 else west,
                d1 if i % 2 else d2,
                in_cluster=i % 3 == 0,
            )
            cls.regular.append(row)
            if i % 4 == 0:
                ssa(row, "2024", _at(2023, 11, 1 + i % 20), _scores(i + 7, 0.0))
            ssa(row, "2025", _at(2024, 11, 1 + i % 25), _scores(i, 0.0))
            ssa(
                row,
                "2026",
                _at(2025, 11, 5 + i % 20),
                _scores(i, ((i % 7) - 3) * 0.35),
                average=i % 5 != 0,
            )
            if i % 5 == 0:
                ssa(row, "2027", _at(2026, 10, 1 + i % 10), _scores(i + 3, 0.2))

        # Several records per FY: the newest confirmed one counts; newer
        # pending, returned and soft-deleted readings count nowhere.
        cls.dup = school("ORC-DUP", central, d1)
        ssa(cls.dup, "2025", _at(2024, 10, 5), _scores(40, 0.0))
        ssa(cls.dup, "2025", _at(2025, 2, 1), _scores(41, 0.0))
        ssa(cls.dup, "2026", _at(2025, 10, 20), _scores(41, 0.5))
        ssa(cls.dup, "2026", _at(2026, 3, 1), _scores(42, 1.0), status="pending")
        ssa(cls.dup, "2026", _at(2026, 4, 1), _scores(43, 1.0), deleted=True)
        ssa(cls.dup, "2026", _at(2026, 5, 1), _scores(44, 1.0), status="returned")

        # Same-date ties, broken by created_at — against insertion order.
        cls.tie = school("ORC-TIE", central, d1, in_cluster=True)
        ssa(cls.tie, "2025", _at(2024, 11, 3), _scores(50, 0.0))
        first = ssa(cls.tie, "2026", _at(2026, 1, 15, 10), _scores(50, 0.4))
        second = ssa(cls.tie, "2026", _at(2026, 1, 15, 10), _scores(50, -0.4))
        stamp = _at(2026, 1, 16)
        SsaRecord.objects.filter(pk=first.pk).update(
            created_at=stamp + timedelta(hours=2)
        )
        SsaRecord.objects.filter(pk=second.pk).update(
            created_at=stamp + timedelta(hours=1)
        )
        cls.tie_winner = first

        # Readings closer than MIN_INTERVAL_DAYS: paired, never compared.
        cls.close = school("ORC-CLOSE", west, d2)
        ssa(cls.close, "2025", _at(2025, 9, 20), _scores(60, 0.0))
        ssa(cls.close, "2026", _at(2025, 10, 15), _scores(60, 0.9))

        # No region, no district, no cluster, no owner: every country lens.
        cls.unplaced = school("ORC-UNPLACED")
        ssa(cls.unplaced, "2025", _at(2024, 12, 2), _scores(70, 0.0))
        ssa(cls.unplaced, "2026", _at(2025, 12, 9), _scores(70, -0.6))

        # Partial scores: only the domains read in both cycles pair.
        cls.partial = school("ORC-PARTIAL", central, d1)
        ssa(cls.partial, "2025", _at(2024, 11, 11), {CB: 4.0, WOG: 5.5, LEAD: 6.1})
        ssa(
            cls.partial,
            "2026",
            _at(2025, 11, 12),
            {LEAD: 6.4, FIN: 8.2, CB: 3.3, SsaIntervention.ENROLMENT.value: 7.0},
        )

        # Missing average score in both cycles.
        cls.no_average = school("ORC-NOAVG", west, d2)
        ssa(cls.no_average, "2025", _at(2024, 11, 20), _scores(80, 0.0), average=False)
        ssa(cls.no_average, "2026", _at(2025, 11, 21), _scores(80, 0.3), average=False)

        # Readings late in the UTC day: Nairobi has already moved to the next
        # date, the exposure window has not.
        cls.utc_edge = school("ORC-UTC", central, d1)
        ssa(cls.utc_edge, "2025", _at(2024, 12, 31, 22, 30), _scores(90, 0.0))
        ssa(cls.utc_edge, "2026", _at(2025, 12, 31, 21, 15), _scores(90, 0.7))

        # One cycle only; disjoint domains; a record with no scores at all; a
        # returned current reading.
        cls.lone = school("ORC-LONE", central, d1)
        ssa(cls.lone, "2026", _at(2025, 11, 30), _scores(100, 0.0))
        cls.disjoint = school("ORC-DISJOINT", central, d1)
        ssa(cls.disjoint, "2025", _at(2024, 11, 30), {CB: 5.0})
        ssa(cls.disjoint, "2026", _at(2025, 11, 30), {WOG: 6.0})
        cls.no_scores = school("ORC-NOSCORES", west, d2)
        ssa(cls.no_scores, "2025", _at(2024, 11, 30), {})
        ssa(cls.no_scores, "2026", _at(2025, 11, 30), _scores(110, 0.2))
        cls.returned = school("ORC-RETURNED", west, d2)
        ssa(cls.returned, "2025", _at(2024, 11, 30), _scores(120, 0.0))
        ssa(
            cls.returned,
            "2026",
            _at(2025, 11, 30),
            _scores(120, 0.4),
            status="returned",
        )

        # Another country, and a closed-down (soft-deleted) school.
        cls.kenya = school("ORC-KENYA", coast, kd)
        ssa(cls.kenya, "2025", _at(2024, 11, 14), _scores(130, 0.0))
        ssa(cls.kenya, "2026", _at(2025, 11, 14), _scores(130, 0.8))
        cls.gone = school("ORC-GONE", central, d1)
        ssa(cls.gone, "2025", _at(2024, 11, 14), _scores(140, 0.0))
        ssa(cls.gone, "2026", _at(2025, 11, 14), _scores(140, 0.8))
        School.objects.filter(pk=cls.gone.pk).update(deleted_at=_at(2026, 2, 1))

        # Published rules: a country threshold ahead of the deployment one, a
        # second deployment threshold, maintain-strong, and another country's.
        _rule("ORC_CB_UG", CB, threshold=Decimal("0.50"), country="Uganda")
        _rule("ORC_CB_ALL", CB, threshold=Decimal("1.00"))
        _rule("ORC_LEAD_ALL", LEAD, threshold=Decimal("0.30"))
        _rule("ORC_FIN_ALL", FIN, direction=ExpectedDirection.MAINTAIN_STRONG)
        _rule("ORC_WOG_KE", WOG, threshold=Decimal("2.00"), country="Kenya")

        _area("spiritual", "Spiritual formation", [CB, WOG])
        _area("leadership", "School leadership", [LEAD, FIN])
        _area(
            "draft",
            "Draft area",
            [SsaIntervention.ENROLMENT.value],
            DefinitionStatus.DRAFT,
        )

        cls.ia = _user("oracle-ia@t.org", EdifyRole.IMPACT_ASSESSMENT.value)
        cls.cd = _user("oracle-cd@t.org", EdifyRole.COUNTRY_DIRECTOR.value)
        cls.pl = _user("oracle-pl@t.org", EdifyRole.COUNTRY_PROGRAM_LEAD.value)
        cls.cceo = _user("oracle-cceo@t.org", EdifyRole.CCEO.value)
        cls.ke_ia = _user(
            "oracle-ke-ia@t.org", EdifyRole.IMPACT_ASSESSMENT.value, "Kenya"
        )
        cls.admin = _user("oracle-admin@t.org", EdifyRole.ADMIN.value, "")
        cls.rvp = _user("oracle-rvp@t.org", EdifyRole.REGIONAL_VICE_PRESIDENT.value)
        StaffSupervisorAssignment.objects.create(
            supervisor=cls.pl.staff_profile, supervisee=cls.cceo.staff_profile
        )
        for row in [*cls.regular[:9], cls.dup, cls.unplaced, cls.partial]:
            StaffSchoolAssignment.objects.create(
                staff=cls.pl.staff_profile, school_id=row.id
            )
        for row in [*cls.regular[9:14], cls.tie, cls.utc_edge, cls.close]:
            StaffSchoolAssignment.objects.create(
                staff=cls.cceo.staff_profile, school_id=row.id
            )
        cls.users = (cls.ia, cls.cd, cls.pl, cls.cceo, cls.ke_ia, cls.admin, cls.rvp)

    def id_lists(self):
        every = list(School.all_objects.values_list("id", flat=True))
        scoped = [
            list(
                scoped_school_queryset(resolve_user_scope(user)).values_list(
                    "id", flat=True
                )
            )
            for user in (self.ia, self.pl, self.cceo, self.ke_ia)
        ]
        return [
            every,
            *scoped,
            [self.disjoint.id, self.no_scores.id],  # paired, nothing in common
            [self.lone.id],  # never paired
            [],
            [self.dup.id, self.dup.id, "no-such-school", self.tie.id],
            list(reversed(every)),
        ]


class ImprovementFrameOracleTests(OracleWorld):
    def test_the_world_reaches_every_edge_case(self):
        frame = _reference_improvement_frame(self.id_lists()[0], "2026")
        paired = set(frame["school_id"])
        self.assertIn(self.tie.id, paired)
        self.assertNotIn(self.lone.id, paired)
        self.assertNotIn(self.disjoint.id, paired)
        self.assertEqual(
            len(frame[frame["school_id"] == self.partial.id]), 2
        )  # CB and LEAD only
        edge = frame[frame["school_id"] == self.utc_edge.id].iloc[0]
        self.assertEqual(edge["window_start"], date(2024, 12, 31))
        self.assertEqual(edge["window_end"], date(2025, 12, 31))
        latest = _reference_latest_confirmed_records([self.tie.id], "2026")
        self.assertEqual(latest[self.tie.id]["id"], self.tie_winner.id)
        self.assertEqual(
            list(_reference_improvement_frame([self.disjoint.id], "2026").columns), []
        )

    def test_latest_confirmed_records_match_the_reference(self):
        for ids in self.id_lists():
            for fy in FYS:
                with self.subTest(n=len(ids), fy=fy):
                    reference = {
                        school_id: (row["id"], row["date_of_ssa"].date())
                        for school_id, row in _reference_latest_confirmed_records(
                            ids, fy
                        ).items()
                    }
                    new = impact_engine._latest_confirmed_records(ids, fy)
                    self.assertEqual(_typed(new), _typed(reference))

    def test_improvement_frame_and_rows_match_the_reference(self):
        for ids in self.id_lists():
            for fy in FYS:
                with self.subTest(n=len(ids), fy=fy):
                    reference = _reference_improvement_frame(ids, fy)
                    new = impact_engine.improvement_frame(ids, fy)
                    pd.testing.assert_frame_equal(new, reference, check_exact=True)
                    self.assertEqual(
                        _typed(new.to_dict("records")),
                        _typed(reference.to_dict("records")),
                    )
                    rows = impact_engine.improvement_rows(ids, fy)
                    if reference.empty and len(reference.columns):
                        self.assertIsNone(rows)  # nobody paired
                    else:
                        self.assertEqual(
                            _typed(rows), _typed(reference.to_dict("records"))
                        )


class PortfolioChangeOracleTests(OracleWorld):
    def _assert_every_scope_matches(self):
        for user in self.users:
            for fy in FYS:
                with self.subTest(role=user.active_role, fy=fy):
                    reference = _reference_portfolio_change(user, fy=fy)
                    new = ia_workflow.portfolio_change(user, fy=fy)
                    self.assertEqual(_typed(new), _typed(reference))
                    self.assertEqual(
                        _typed(ia_workflow.outcome_progress(user, fy=fy)["tiles"]),
                        _typed(portfolio_tiles(reference)),
                    )

    def test_the_world_reaches_every_classification(self):
        portfolio = _reference_portfolio_change(self.ia, fy="2026")
        self.assertGreaterEqual(portfolio["measured"], 20)
        self.assertTrue(portfolio["improved"] and portfolio["declined"])
        self.assertTrue(any(row.get("maintained") for row in portfolio["rows"]))
        self.assertTrue(
            any(row.get("median_change") is not None for row in portfolio["rows"])
        )
        self.assertEqual(sum(1 for row in portfolio["rows"] if row["is_area"]), 3)
        pl = _reference_portfolio_change(self.pl, fy="2026")
        self.assertTrue(0 < pl["schools_in_scope"] < portfolio["schools_in_scope"])
        cceo = _reference_portfolio_change(self.cceo, fy="2026")
        self.assertTrue(any(row.get("withheld") for row in cceo["rows"]))

    def test_every_scope_and_year_matches_the_reference(self):
        self._assert_every_scope_matches()

    def test_matches_with_no_approved_outcome_area(self):
        # One unclaimed group holds every domain: the portfolio's verdicts are
        # reused for it.
        OutcomeArea.objects.all().delete()
        self.assertEqual(len(_outcome_area_groups()), 1)
        self._assert_every_scope_matches()

    def test_matches_when_nothing_is_comparable(self):
        SsaRecord.objects.filter(fy="2025").update(date_of_ssa=_at(2025, 11, 1))
        self._assert_every_scope_matches()
