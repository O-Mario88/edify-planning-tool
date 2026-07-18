from __future__ import annotations

from collections import defaultdict

from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.http import HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.core.permissions import require_page_permission

from .forms import HelpArticleForm
from .models import HelpArticle, HelpArticleRoleAccess, HelpArticleRouteContext, HelpArticleState, HelpCategory, HelpGlossaryTerm, HelpReleaseNote
from .services import (
    article_for_slug,
    create_revision,
    contextual_article,
    documentation_drift_report,
    ensure_canonical_content,
    excerpt,
    personalized_articles,
    mark_review_due_articles,
    record_feedback,
    result_match_reason,
    search_articles,
    slug_for_role,
    sync_route_contexts,
    transition_article,
    visible_articles,
)


TOPIC_ICONS = {
    "getting-started": "compass",
    "role-guides": "person",
    "workflows": "route",
    "features": "spark",
    "ssa-school-improvement": "school",
    "planning-field-operations": "calendar",
    "finance-accountability": "wallet",
    "evidence-verification": "check",
    "targets-analytics": "chart",
    "hr-people": "people",
    "administration-security": "shield",
    "troubleshooting": "lifebuoy",
    "glossary": "book",
}

TOPIC_TONES = {
    "getting-started": "sky",
    "role-guides": "violet",
    "workflows": "indigo",
    "features": "amber",
    "ssa-school-improvement": "emerald",
    "planning-field-operations": "blue",
    "finance-accountability": "rose",
    "evidence-verification": "teal",
    "targets-analytics": "cyan",
    "hr-people": "fuchsia",
    "administration-security": "slate",
    "troubleshooting": "orange",
    "glossary": "purple",
}


def _topic_cards(role: str) -> list[dict]:
    """Build the support-center cards in one pass without per-card queries."""
    articles_by_category: dict[str, list[HelpArticle]] = defaultdict(list)
    for article in visible_articles(role).order_by("category__sort_order", "title"):
        articles_by_category[article.category.slug].append(article)

    cards = []
    for category in HelpCategory.objects.all():
        articles = articles_by_category.get(category.slug, [])
        if not articles:
            continue
        cards.append({
            "category": category,
            "articles": articles[:3],
            "count": len(articles),
            "icon": TOPIC_ICONS.get(category.slug, "book"),
            "tone": TOPIC_TONES.get(category.slug, "sky"),
        })
    return cards


def _role(request) -> str:
    return getattr(request.user, "active_role", "")


def _role_from_slug(role_slug: str) -> str:
    from apps.core.rbac import EdifyRole
    from django.utils.text import slugify

    for role in EdifyRole:
        if role_slug in {slugify(role.value), slugify(role.name), role.value.lower()}:
            return role.value
    return role_slug


def _article_or_denied(slug: str, role: str):
    article = get_object_or_404(HelpArticle, slug=slug)
    if not article_for_slug(slug, role):
        raise PermissionDenied("This guidance is not available for your active role.")
    return article


def _manager_required(request):
    if not (getattr(request.user, "is_staff", False) or _role(request) == "Admin"):
        raise PermissionDenied("Only an authorised Admin can manage Help content.")


@require_page_permission("help")
def home(request):
    ensure_canonical_content()
    mark_review_due_articles()
    if not HelpArticleRouteContext.objects.exists():
        sync_route_contexts()
    role = _role(request)
    articles = visible_articles(role)
    topic_cards = _topic_cards(role)
    context = {
        "topic_cards": topic_cards,
        "help_stats": [
            {"value": sum(topic["count"] for topic in topic_cards), "label": "guides for your role"},
            {"value": len(topic_cards), "label": "learning topics"},
            {"value": "Step-by-step", "label": "plain-language lessons"},
        ],
        "continue_learning": personalized_articles(role, 5),
        "role_article": article_for_slug(slug_for_role(role), role),
        "popular_workflows": articles.filter(workflow__gt="").order_by("title")[:6],
        "recent_articles": articles.order_by("-last_reviewed_at")[:5],
        "common_problems": articles.filter(feature="troubleshooting").order_by("title")[:6],
        "glossary_terms": HelpGlossaryTerm.objects.all()[:8],
        "release_notes": HelpReleaseNote.objects.all()[:3],
        "help_role": role,
    }
    return render(request, "pages/help/index.html", context)


@require_page_permission("help")
def search(request):
    ensure_canonical_content()
    query = request.GET.get("q", "").strip()
    role = _role(request)
    articles = list(search_articles(query, role)[:40])
    results = [
        {"article": article, "excerpt": excerpt(article, query), "reason": result_match_reason(article, query)}
        for article in articles
    ]
    return render(request, "pages/help/search.html", {"query": query, "results": results})


@require_page_permission("help")
def category(request, slug):
    category = get_object_or_404(HelpCategory, slug=slug)
    return render(request, "pages/help/category.html", {"category": category, "articles": visible_articles(_role(request)).filter(category=category)})


@require_page_permission("help")
def role_guide(request, role_slug):
    return article(request, slug_for_role(_role_from_slug(role_slug)))


@require_page_permission("help")
def workflow(request, workflow_slug):
    return article(request, "workflow-" + workflow_slug.removeprefix("workflow-"))


@require_page_permission("help")
def feature(request, feature_slug):
    return article(request, "feature-" + feature_slug.removeprefix("feature-"))


@require_page_permission("help")
def article(request, slug):
    ensure_canonical_content()
    item = get_object_or_404(HelpArticle, slug=slug)
    # Return an explicit 403 here rather than redirecting to a general access
    # page. Search results must not leak restricted titles, and a copied Help
    # URL should make the access decision unambiguous to the caller.
    if not article_for_slug(slug, _role(request)):
        return HttpResponseForbidden("This guidance is not available for your active role.")
    return render(request, "pages/help/article.html", {"article": item, "related": item.related_articles.all()})


@require_page_permission("help")
def troubleshooting(request):
    return render(request, "pages/help/category.html", {
        "category": HelpCategory.objects.get(slug="troubleshooting"),
        "articles": visible_articles(_role(request)).filter(feature="troubleshooting"),
    })


@require_page_permission("help")
def glossary(request):
    query = request.GET.get("q", "").strip()
    terms = HelpGlossaryTerm.objects.all()
    if query:
        terms = terms.filter(term__icontains=query) | terms.filter(definition__icontains=query)
    return render(request, "pages/help/glossary.html", {"terms": terms, "query": query})


@require_page_permission("help")
def release_notes(request):
    return render(request, "pages/help/release_notes.html", {"release_notes": HelpReleaseNote.objects.prefetch_related("related_articles")})


@require_page_permission("help")
def contextual(request):
    path = request.GET.get("for", "/").strip() or "/"
    status = request.GET.get("status", "").strip()
    item = contextual_article(path, _role(request), status)
    if not item:
        return HttpResponseForbidden("No authorised contextual help is available.")
    walkthrough = item.walkthroughs.filter(active=True).first()
    return render(request, "partials/help/contextual_dialog.html", {"article": item, "path": path, "walkthrough": walkthrough})


@require_POST
@require_page_permission("help")
def feedback(request, slug):
    item = _article_or_denied(slug, _role(request))
    feedback_type = request.POST.get("feedback_type", "helpful")
    helpful = True if feedback_type == "helpful" else False if feedback_type == "outdated" else None
    record_feedback(
        article=item, user=request.user, helpful=helpful, feedback_type=feedback_type,
        comment=request.POST.get("comment", ""), page_context=request.POST.get("page_context", ""),
    )
    messages.success(request, "Thanks — your feedback has been recorded for the documentation review queue.")
    return redirect("frontend:help_article", slug=item.slug)


@require_page_permission("help")
def print_article(request, slug):
    item = _article_or_denied(slug, _role(request))
    return render(request, "pages/help/print_article.html", {"article": item})


@require_page_permission("help")
def role_manual_export(request, role_slug):
    role = role_slug.replace("-", " ").title()
    if role != _role(request) and not (getattr(request.user, "is_staff", False) or _role(request) == "Admin"):
        raise PermissionDenied("You can export only your own role manual.")
    articles = visible_articles(role)
    response = render(request, "pages/help/manual_export.html", {"manual_title": f"{role} Manual", "articles": articles, "role": role})
    response["Content-Disposition"] = f'attachment; filename="edify-{role_slug}-manual.html"'
    return response


@require_page_permission("help")
def complete_manual_export(request):
    _manager_required(request)
    response = render(request, "pages/help/manual_export.html", {"manual_title": "Edify Authorised Manual", "articles": visible_articles(None), "role": "Authorised administration"})
    response["Content-Disposition"] = 'attachment; filename="edify-authorised-manual.html"'
    return response


@require_page_permission("help")
def manage(request):
    _manager_required(request)
    report = documentation_drift_report()
    return render(request, "pages/help/manage.html", {"articles": HelpArticle.objects.select_related("category").all(), "report": report})


@require_page_permission("help")
def manage_article(request, slug=None):
    _manager_required(request)
    instance = get_object_or_404(HelpArticle, slug=slug) if slug else None
    if instance and instance.state != HelpArticleState.DRAFT:
        messages.error(request, "Published and in-review articles are immutable. Create a revision draft so the live manual stays available during review.")
        return redirect("frontend:help_manage")
    if request.method == "POST":
        form = HelpArticleForm(request.POST, instance=instance)
        if form.is_valid():
            item = form.save(commit=False)
            if instance is None:
                item.author = request.user
                item.state = HelpArticleState.DRAFT
            item.save()
            item.rebuild_search_document(save=True)
            HelpArticleRoleAccess.objects.filter(article=item).delete()
            HelpArticleRoleAccess.objects.bulk_create([HelpArticleRoleAccess(article=item, role=role) for role in form.cleaned_data["roles"]])
            HelpArticleRouteContext.objects.filter(article=item).delete()
            HelpArticleRouteContext.objects.bulk_create([
                HelpArticleRouteContext(article=item, route_pattern=route.strip(), priority=10)
                for route in form.cleaned_data["route_patterns"].splitlines() if route.strip()
            ])
            messages.success(request, "Draft saved. Submit it through technical and product review before publishing.")
            return redirect("frontend:help_manage")
    else:
        form = HelpArticleForm(instance=instance)
    return render(request, "pages/help/edit_article.html", {"form": form, "article": instance})


@require_POST
@require_page_permission("help")
def manage_revision(request, slug):
    _manager_required(request)
    source = get_object_or_404(HelpArticle, slug=slug)
    revision = create_revision(source, request.user)
    messages.success(request, "A separate revision draft was created. The published article remains visible until you publish and archive the predecessor.")
    return redirect("frontend:help_manage_article", slug=revision.slug)


@require_POST
@require_page_permission("help")
def manage_transition(request, slug, action):
    _manager_required(request)
    item = get_object_or_404(HelpArticle, slug=slug)
    try:
        transition_article(item, action, request.user, change_summary=request.POST.get("change_summary", ""))
    except ValueError as exc:
        messages.error(request, str(exc))
    else:
        messages.success(request, f"Article {action.replace('_', ' ')} completed with an auditable version entry.")
    return redirect("frontend:help_manage")
