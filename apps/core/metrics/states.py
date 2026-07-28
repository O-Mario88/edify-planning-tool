"""The six things a metric can mean when it has no number to show.

Every KPI on the platform currently collapses these into ``0``. A school with
no SSA record, a role the metric does not apply to, a partner with a sample too
small to average, and a genuine measured zero all render as the same character,
so a reader cannot tell "nothing happened" from "we did not ask" from "we
cannot know yet". That is not a formatting nicety: schools with no verified SSA
were being pulled into the low-performing-intervention counts *as zeroes*, which
makes a missing measurement look like a bad one.

A measured zero is a fact and must still display as ``0``. The other five are
absences, and each one tells the reader to do something different -- collect the
data, ignore the tile, wait for the follow-up cycle, widen the sample, or
configure the backend. ``MEASURED`` is therefore the only state that carries a
number; the rest carry a reason.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class DataState(str, Enum):
    """Why a metric does or does not have a number."""

    # A real, measured value. ``0`` here means "we looked, and it was zero".
    MEASURED = "measured"

    # No source records exist for this scope and period at all.
    NO_DATA = "no_data"

    # The metric is meaningless for this role or context (partner payment
    # status on a page for a role that never pays partners).
    NOT_APPLICABLE = "not_applicable"

    # The inputs exist but the follow-up needed to compute it has not happened
    # yet -- an SSA delta before the second annual assessment, say.
    NOT_YET_MEASURABLE = "not_yet_measurable"

    # There are records, but too few to report honestly (an average over two
    # schools presented as a country figure).
    INSUFFICIENT_DATA = "insufficient_data"

    # A backend prerequisite is missing: no cost catalogue, no target set, no
    # FY baseline locked. The reader cannot fix this by doing fieldwork.
    CONFIGURATION_REQUIRED = "configuration_required"

    @property
    def is_measured(self) -> bool:
        return self is DataState.MEASURED


# What each absence says on the card. Deliberately plain: the reader should
# learn what to do next without opening a tooltip.
DEFAULT_STATE_TEXT: dict[DataState, str] = {
    DataState.NO_DATA: "No data",
    DataState.NOT_APPLICABLE: "Not applicable",
    DataState.NOT_YET_MEASURABLE: "Not yet measurable",
    DataState.INSUFFICIENT_DATA: "Insufficient data",
    DataState.CONFIGURATION_REQUIRED: "Setup required",
}


@dataclass(frozen=True)
class MetricValue:
    """A metric's number together with the reason it is or is not there.

    Services return this instead of a bare int/float/str so that the decision
    "is this a zero or an absence?" is made once, where the query ran and the
    context is known -- not in a template that only ever sees the digit.
    """

    state: DataState
    value: int | float | None = None
    # Denominator for any ratio metric. Section 24: a progress bar without one
    # is not a progress bar, and 0/0 must never render as 100%.
    denominator: int | float | None = None
    # Overrides DEFAULT_STATE_TEXT when the reason is worth naming precisely
    # ("No approved requests for August").
    note: str | None = None

    def __post_init__(self) -> None:
        if self.state.is_measured and self.value is None:
            raise ValueError("A MEASURED metric must carry a value")
        if not self.state.is_measured and self.value is not None:
            raise ValueError(
                f"{self.state.value} carries a reason, not a value -- "
                "an absence rendered as a number is the bug this class exists "
                "to prevent"
            )

    @classmethod
    def measured(
        cls,
        value: int | float,
        *,
        denominator: int | float | None = None,
        note: str | None = None,
    ) -> "MetricValue":
        return cls(
            state=DataState.MEASURED,
            value=value,
            denominator=denominator,
            note=note,
        )

    @classmethod
    def absent(cls, state: DataState, *, note: str | None = None) -> "MetricValue":
        if state.is_measured:
            raise ValueError("absent() is for the five non-measured states")
        return cls(state=state, note=note)

    @classmethod
    def ratio(
        cls,
        numerator: int | float,
        denominator: int | float,
        *,
        empty_state: DataState = DataState.NO_DATA,
        note: str | None = None,
    ) -> "MetricValue":
        """A percentage, or an honest absence when the denominator is empty.

        The whole reason this helper exists: ``0/0`` is not ``100%`` and it is
        not ``0%``. It is "there was nothing to measure", and every ratio on
        the platform has to answer that the same way.
        """
        if not denominator:
            return cls.absent(empty_state, note=note)
        return cls.measured(
            round(numerator / denominator * 100, 1),
            denominator=denominator,
            note=note,
        )

    @property
    def display_text(self) -> str | None:
        """Text to show in place of a number, or None when there is a number."""
        if self.state.is_measured:
            return None
        return self.note or DEFAULT_STATE_TEXT[self.state]
