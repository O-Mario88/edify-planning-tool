"""Descriptive statistics of a school portfolio.

Pure functions over values. No business rule lives here: which schools belong
to a portfolio, and who may see them, is decided by the Go gateway before a
single row reaches this module.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from statistics import median
from types import MappingProxyType


@dataclass(frozen=True)
class SchoolFact:
    """The little of a school the worker is told."""

    school_type: str
    enrollment: int | None


@dataclass(frozen=True)
class PortfolioSummary:
    school_count: int
    schools_by_type: Mapping[str, int]
    schools_with_enrollment: int
    total_enrollment: int
    median_enrollment: float


def summarize(facts: Iterable[SchoolFact]) -> PortfolioSummary:
    """Summarise a portfolio. Schools without an enrolment figure count as
    schools but are left out of the enrolment statistics; they are not zeros."""
    rows = tuple(facts)
    enrollments = [row.enrollment for row in rows if row.enrollment is not None]
    return PortfolioSummary(
        school_count=len(rows),
        schools_by_type=MappingProxyType(dict(Counter(row.school_type for row in rows))),
        schools_with_enrollment=len(enrollments),
        total_enrollment=sum(enrollments),
        median_enrollment=float(median(enrollments)) if enrollments else 0.0,
    )
