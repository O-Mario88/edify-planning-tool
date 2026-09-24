"""classify_pairs decides each rule and each interval once, unchanged.

An IA dashboard at 50,000 schools classifies 160,000 domain pairs on every
load, and each one looked up its rule and re-measured its school's two dates
(2026-09-24 A+ audit). The loop now decides those once per (domain, country)
and once per pair of dates. This holds it to the per-row loop it replaced,
frozen below, over rows that reach every branch of change_between.
"""

from __future__ import annotations

import random
from datetime import date, datetime, timedelta, timezone as dt_tz
from types import SimpleNamespace

from django.test import SimpleTestCase

from apps.core.enums import SsaIntervention
from apps.ssa import change_rules
from apps.ssa.change_rules import NOT_COMPARABLE, RuleBook, change_between


def _per_row(rows, *, book, country_for=None):
    """classify_pairs as it stood before, frozen as the oracle."""
    country_for = country_for or (lambda _school_id: "")
    out = []
    for row in rows:
        intervention = row.get("intervention") or ""
        result = change_between(
            row.get("prev_score"),
            row.get("curr_score"),
            intervention,
            rule=book.rule(intervention, country_for(row.get("school_id"))),
            before_on=row.get("window_start"),
            after_on=row.get("window_end"),
        )
        if result["classification"] == NOT_COMPARABLE:
            continue
        out.append({**row, **result})
    return out


def _book():
    codes = [c[0] for c in SsaIntervention.choices]
    rule = lambda n, code, country, change, direction: SimpleNamespace(  # noqa: E731
        id=f"map{n}",
        intervention=code,
        country=country,
        version=n,
        expected_direction=direction,
        min_meaningful_change=change,
    )
    return RuleBook(
        [
            rule(1, codes[0], "", 0.5, "improve"),
            rule(2, codes[0], "Kenya", 1.0, "improve"),
            rule(3, codes[1], "", None, "improve"),
            rule(4, codes[2], "", None, "maintain_strong"),
            rule(5, codes[3], " Uganda ", -0.25, "improve"),
        ]
    )


def _rows(seed, n=4000):
    rnd = random.Random(seed)
    codes = [c[0] for c in SsaIntervention.choices] + ["", None]
    start = date(2025, 1, 1)
    rows = []
    for i in range(n // 8):
        school = f"s{i % 300}"
        kind = rnd.random()
        before = start + timedelta(days=rnd.randrange(0, 60))
        after = before + timedelta(days=rnd.choice([0, 30, 119, 120, 121, 365]))
        if kind < 0.1:
            before = None
        elif kind < 0.2:
            after = None
        elif kind < 0.4:
            before = datetime.combine(before, datetime.min.time(), tzinfo=dt_tz.utc)
            after = datetime.combine(after, datetime.max.time(), tzinfo=dt_tz.utc)
        for code in rnd.sample(codes, 8):
            prev = None if rnd.random() < 0.05 else round(rnd.uniform(0, 10), 1)
            curr = None if rnd.random() < 0.05 else round(rnd.uniform(0, 10), 1)
            rows.append(
                {
                    "school_id": school,
                    "intervention": code,
                    "prev_score": prev,
                    "curr_score": curr,
                    "delta": None if prev is None or curr is None else curr - prev,
                    "window_start": before,
                    "window_end": after,
                }
            )
    return rows


class ClassifyPairsEquivalenceTest(SimpleTestCase):
    def test_every_branch_matches_the_per_row_loop(self):
        book = _book()
        countries = {
            f"s{i}": ["", "Kenya", "Uganda", " Uganda "][i % 4] for i in range(300)
        }
        for seed in range(5):
            rows = _rows(seed)
            with self.subTest(seed=seed):
                for country_for in (None, countries.get, lambda s: countries[s] or ""):
                    expected = _per_row(rows, book=book, country_for=country_for)
                    got = change_rules.classify_pairs(
                        rows, book=book, country_for=country_for
                    )
                    self.assertEqual(got, expected)
                # The fixture reaches every classification.
                seen = {p["classification"] for p in expected}
                self.assertEqual(
                    seen,
                    {
                        change_rules.IMPROVED,
                        change_rules.DECLINED,
                        change_rules.NO_CHANGE,
                        change_rules.MAINTAINED_STRONG,
                    },
                )
                self.assertLess(len(expected), len(rows))

    def test_the_rule_dicts_are_the_books_own(self):
        book = _book()
        rows = _rows(7, 400)
        got = change_rules.classify_pairs(rows, book=book)
        expected = _per_row(rows, book=book)
        self.assertEqual(
            [p["rule_label"] for p in got], [p["rule_label"] for p in expected]
        )
