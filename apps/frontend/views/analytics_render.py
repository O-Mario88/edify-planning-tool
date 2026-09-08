"""One renderer for every Analytics section.

The Analytics workspace is one page: the header, the filter row, the tiles and
the tablist are written once in `pages/analytics/workspace.html`, and a tab
swaps only the panel (owner, 2026-09-05: "replace links with tab roles and
display only what needs to be displayed under tab roles ... consolidate
everything in the headers, filters, and tiles for them to stay fixed").

A section view therefore never picks a template. It hands its context to
`render_analytics_section` with the partial holding its own content, and this
decides which of the three shapes the request asked for:

  panel   a tab was clicked         → just that section's content
  scope   the filters changed       → tiles + tablist + frame + panel, so a
                                      new scope moves the tiles and the panel
                                      together and they cannot disagree
  page    a deep link or a reload   → the whole shell around the same panel,
                                      so a bookmark and a tab click are the
                                      same page

Keeping the choice here means a section view stays a view: it fetches its data
and names its panel.
"""

from __future__ import annotations

from django.shortcuts import render

WORKSPACE_TEMPLATE = "pages/analytics/workspace.html"
SCOPE_TEMPLATE = "partials/analytics/scope.html"
PANEL_TEMPLATE = "partials/analytics/panel.html"
TILES_TEMPLATE = "partials/analytics/executive_pulse.html"


def _scope_tiles(request, context: dict) -> dict:
    """The workspace tile strip, on every tab.

    The tiles describe the SCOPE the filters ask for, not the tab, so they are
    the same four signals wherever you are in the workspace — which is what
    keeps them fixed rather than appearing on one section and vanishing on the
    next. The overview has already computed them; every other section reads
    the same cached dataset, so this costs a cache hit rather than a rebuild.
    """
    if context.get("executive_kpi_items"):
        return context
    try:
        from apps.frontend.views.analytics_views import analytics_scope_kpis

        return {**context, **analytics_scope_kpis(request)}
    except Exception:  # noqa: BLE001 — tiles are context, never the page
        return context


def render_analytics_section(
    request,
    panel_template: str,
    context: dict,
    *,
    section_key: str = "",
    panel_title: str = "",
    tiles_template: str = "",
    filters_template: str = "",
    frame: dict | None = None,
):
    """Render one Analytics section in whichever shape the request asked for."""
    frame = frame or {}
    context = {
        **context,
        "panel_template": panel_template,
        "active_section_key": section_key,
        "panel_title": panel_title,
        "tiles_template": tiles_template,
        "filters_template": filters_template,
        "frame_question": frame.get("question"),
        "frame_evidence": frame.get("evidence"),
        "frame_freshness": frame.get("freshness"),
        "frame_confidence": frame.get("confidence"),
    }
    context = _scope_tiles(request, context)
    if not context.get("tiles_template") and context.get("executive_kpi_items"):
        context["tiles_template"] = TILES_TEMPLATE

    target = request.headers.get("HX-Target")
    if target == "analytics-panel":
        return render(request, PANEL_TEMPLATE, context)
    if target == "analytics-scope":
        return render(request, SCOPE_TEMPLATE, context)
    if request.headers.get("HX-Request") == "true" and not target:
        # An HTMX request that names no target — a boosted link, a
        # programmatic fetch — still asked for a fragment, not a page with a
        # <head> and a shell around it. The scope is the largest fragment the
        # workspace has: the filter row, the tiles, the tablist and the panel.
        return render(request, SCOPE_TEMPLATE, context)
    return render(request, WORKSPACE_TEMPLATE, context)
