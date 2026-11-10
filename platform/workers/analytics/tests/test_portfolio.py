import pytest

from edify_analytics.portfolio import SchoolFact, summarize


def test_empty_portfolio_is_all_zeros():
    summary = summarize([])

    assert summary.school_count == 0
    assert dict(summary.schools_by_type) == {}
    assert summary.schools_with_enrollment == 0
    assert summary.total_enrollment == 0
    assert summary.median_enrollment == 0.0


def test_schools_without_an_enrollment_figure_are_counted_but_not_averaged():
    summary = summarize(
        [
            SchoolFact("client", 100),
            SchoolFact("client", None),
            SchoolFact("core", 300),
        ]
    )

    assert summary.school_count == 3
    assert dict(summary.schools_by_type) == {"client": 2, "core": 1}
    assert summary.schools_with_enrollment == 2
    assert summary.total_enrollment == 400
    assert summary.median_enrollment == 200.0


@pytest.mark.parametrize(
    ("enrollments", "expected"),
    [([5], 5.0), ([1, 2, 3], 2.0), ([1, 2, 3, 10], 2.5), ([0, 0, 9], 0.0)],
)
def test_median(enrollments, expected):
    summary = summarize(SchoolFact("client", value) for value in enrollments)

    assert summary.median_enrollment == expected


def test_a_recorded_enrollment_of_zero_is_a_figure():
    summary = summarize([SchoolFact("client", 0)])

    assert summary.schools_with_enrollment == 1


def test_the_summary_cannot_be_mutated():
    summary = summarize([SchoolFact("client", 1)])

    with pytest.raises(TypeError):
        summary.schools_by_type["client"] = 99
    with pytest.raises(AttributeError):
        summary.school_count = 99
