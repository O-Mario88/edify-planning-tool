"""Leadership pages that read decisions and their evidence.

Decision Intelligence, the page for the leadership and budget engines, left
with the Analytics entry; its review is on the Country Profile now
(views/profile_decisions.py, owner, 2026-10-19).
"""

from __future__ import annotations

from apps.core.permissions import require_page_permission


@require_page_permission("decision_log")
def decision_log_view(request):
    """Who decided what, scoped to the reader.

    A tamper-evident audit chain already existed, but every surface that reads
    it was Admin-, HR- or Accountant-only — so the roles with the most
    consequential powers had no way to see what had been decided.
    """
    from apps.audit.decision_log_service import decision_log

    from apps.frontend.views.analytics_render import render_analytics_section

    return render_analytics_section(
        request,
        "partials/analytics/panels/decision_log.html",
        {"log": decision_log(request.user, request.GET.dict())},
        section_key="decision_log",
        panel_title="Decision Log",
        frame={
            "question": (
                "What was decided, by whom, on what record, and with what "
                "stated reason?"
            ),
            "evidence": "Tamper-evident audit chain",
            "freshness": "Selected lookback window",
            "confidence": "System-recorded history",
        },
    )
