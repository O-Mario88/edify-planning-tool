"""Presentation helpers shared by Project-backed planning drawers."""

from apps.core.enums import SsaIntervention

from .models import Project


def training_project_options() -> list[dict]:
    """Every created Project, annotated for the Group Training picker.

    Paused, closed, or incompletely configured Projects remain visible so the
    dropdown is an honest inventory, but are disabled because they cannot
    accept a new scheduled commitment.
    """
    labels = dict(SsaIntervention.choices)
    options = []
    for project in Project.objects.filter(deleted_at__isnull=True).order_by("name"):
        primary, secondary = project.intervention_plan()
        targets = [value for value in [primary, *secondary] if value]
        selectable = project.accepts_new_work and bool(primary)
        if not project.accepts_new_work:
            unavailable_reason = project.status_label
        elif not primary:
            unavailable_reason = "SSA intervention not configured"
        else:
            unavailable_reason = ""
        options.append(
            {
                "id": project.id,
                "name": project.name,
                "code": project.code or "",
                "status": project.status,
                "statusLabel": project.status_label,
                "selectable": selectable,
                "unavailableReason": unavailable_reason,
                "primaryIntervention": primary or "",
                "secondaryInterventions": secondary,
                "interventions": targets,
                "interventionLabels": [
                    labels.get(value, value.replace("_", " ").title())
                    for value in targets
                ],
            }
        )
    return options


__all__ = ["training_project_options"]
