from __future__ import annotations

from apps.core.exceptions import BadRequest


class ReasonRequiredError(BadRequest):
    """Soft-block: scheduling fewer schools than the CD's daily target is
    allowed, but only with a non-empty reason. The caller (view layer) should
    catch this distinctly from a plain BadRequest to re-render the form with
    a reason field instead of a flat error message."""

    default_detail = "A reason is required when scheduling below the daily target."
