"""Global search across schools, partners, activities."""
from __future__ import annotations

from django.db.models import Q

from apps.core.scoping import resolve_user_scope, school_queryset


def search(principal, q: str, context: str | None = None) -> dict:
    q = (q or "").strip()
    if not q:
        return {"query": q, "context": context, "results": []}
    scope = resolve_user_scope(principal)
    results: list[dict] = []

    # Schools (scope-constrained).
    base = school_queryset(scope)
    if base is not None:
        for s in base.filter(Q(name__icontains=q) | Q(school_id__icontains=q))[:20]:
            results.append({
                "kind": "school",
                "id": s.id,
                "label": s.name,
                "sub": s.school_id,
                "route": f"/schools/{s.school_id}",
            })

    # Partners.
    if scope.can_view_partner_data:
        from apps.partners.models import Partner

        for p in Partner.objects.filter(name__icontains=q, deleted_at__isnull=True)[:10]:
            results.append({"kind": "partner", "id": p.id, "label": p.name, "route": "/partners"})

    return {"query": q, "context": context, "results": results}
