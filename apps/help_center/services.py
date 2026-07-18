"""Canonical content seeding, access filtering, publishing and drift checks."""

from __future__ import annotations

from datetime import timedelta

from django.db import transaction
from django.db.models import Max, Q
from django.urls import URLPattern, resolve
from django.utils import timezone
from django.utils.text import slugify

from .catalog import CATEGORIES, FEATURES, GLOSSARY, ROLE_GUIDES, TROUBLESHOOTING, WORKFLOWS
from .learning import build_learning_sections
from .models import (
    HelpArticle,
    HelpArticleFeedback,
    HelpArticleRoleAccess,
    HelpArticleRouteContext,
    HelpArticleState,
    HelpArticleVersion,
    HelpCategory,
    HelpGlossaryTerm,
    HelpReleaseNote,
    HelpSearchKeyword,
    HelpWalkthrough,
    article_snapshot,
)


CANONICAL_REVIEWER = "Edify guide review"
REVIEW_INTERVAL_DAYS = 180
SYNONYMS = {
    "sf id": "salesforce activity id",
    "salesforce id": "salesforce activity id",
    "activity id": "salesforce activity id",
    "accountability code": "netsuite expense id",
    "netsuite id": "netsuite expense id",
    "school assessment": "ssa",
    "fund request": "weekly fund request",
    "advance request": "weekly fund request",
    "weekly request": "weekly fund request",
}


def _friendly_summary(summary: str) -> str:
    """Keep the precise meaning, but use words a day-to-day user will recognise."""
    replacements = (
        (
            "When a user schedules work, the canonical costing service validates the date, fiscal period, participant requirements and active rate card. It persists ActivityScheduleCostLine snapshots in whole UGX; manual price invention is not supported.",
            "When you schedule work, Edify checks the date, financial period, required number of participants and current rate card. It saves the cost in whole UGX. You cannot type in a made-up price.",
        ),
        ("ActivityScheduleCostLine snapshots", "a saved copy of the cost"),
        ("ActivityScheduleCostLine", "saved activity cost"),
        ("returned_by_ia", "a returned flag"),
        ("RBAC matrix", "roles and permissions list"),
        ("manual price invention is not supported", "you cannot type in a made-up price"),
        ("participant requirements", "required number of participants"),
        ("validates", "checks"),
        ("canonical", "official"),
        ("authoritative", "official"),
        ("authorised", "allowed"),
        ("operational ledger", "main activity record"),
        ("source record", "main record"),
        ("source workspace", "main page"),
        ("source activities", "activities"),
        ("source values", "current values"),
        ("source workflow", "main workflow"),
        ("role- and scope-aware", "based on your role and what you are allowed to see"),
        ("role-specific", "for the right role"),
        ("scoped", "limited"),
        ("scope", "work area"),
        ("persists", "saves"),
        ("immutable-at-schedule", "saved when you schedule"),
        ("immutable", "locked"),
        ("atomicity", "saving the whole upload together"),
        ("gates", "checks"),
        ("handoff", "next step"),
        ("rework state", "sent-back-for-correction state"),
        ("traceable", "easy to follow"),
    )
    for technical, everyday in replacements:
        summary = summary.replace(technical, everyday)
    return summary


def _standard_sections(
    *,
    title: str,
    category: str,
    roles: list[str],
    routes: list[str],
    purpose: str,
    steps: list[str],
    sources: list[str],
    feature: str = "",
    workflow: str = "",
    statuses: list[str] | None = None,
    next_actor: str = "The next authorised workflow owner",
) -> list[dict]:
    return build_learning_sections(
        title=title,
        category=category,
        roles=roles,
        purpose=purpose,
        steps=steps,
        statuses=statuses,
        next_actor=next_actor,
    )


def _article_spec(
    *, title: str, slug: str, category: str, roles: list[str], summary: str,
    routes: list[str], sources: list[str], keywords: list[str], steps: list[str],
    feature: str = "", workflow: str = "", next_actor: str = "the next authorised workflow owner",
) -> dict:
    summary = _friendly_summary(summary)
    steps = [_friendly_summary(step) for step in steps]
    return {
        "title": title,
        "slug": slug,
        "category": category,
        "roles": roles,
        "summary": summary,
        "routes": routes,
        "sources": sources,
        "keywords": keywords,
        "feature": feature,
        "workflow": workflow,
        "content": _standard_sections(
            title=title, category=category, roles=roles, routes=routes,
            purpose=summary, steps=steps, sources=sources, feature=feature,
            workflow=workflow, next_actor=next_actor,
        ),
    }


def canonical_specs() -> list[dict]:
    specs: list[dict] = []
    specs.append(_article_spec(
        title="Getting Started with Edify", slug="getting-started", category="Getting Started",
        roles=[role for role, *_ in []] or ["CCEO", "Program Lead", "CountryDirector", "ImpactAssessment", "RegionalVicePresident", "HumanResources", "Accountant", "PartnerAdmin", "PartnerFieldOfficer", "ProjectCoordinator", "Admin"],
        summary="Edify connects school intelligence, planning, field delivery, evidence, finance clearance, targets and the next planning cycle through one set of source records.",
        routes=["help"], sources=["apps/frontend/urls.py", "apps/activities/models.py", "apps/core/rbac.py"],
        keywords=["orientation", "workflow", "help", "manual"], feature="help", workflow="ecosystem",
        steps=["Choose your active role and use the role guide matched to it.", "Start from the source record: School, Cluster, Activity, fund request or people record.", "Use the next-action/status on that record; do not infer completion from a dashboard alone.", "Use Contextual Help on any workspace to open the relevant article."],
    ))
    for slug, title, roles, summary, responsibilities, sources in ROLE_GUIDES:
        specs.append(_article_spec(
            title=f"{title} Guide", slug=f"role-{slug}", category="Role Guides", roles=roles,
            summary=summary, routes=["dashboard", "help/roles"], sources=sources,
            keywords=[title, "role guide", "daily responsibilities", "escalation"],
            steps=responsibilities, feature="role-guide", workflow="role-guide",
            next_actor="the authorised person or team described by the live workflow",
        ))
    for slug, title, category, roles, summary, sources in WORKFLOWS:
        specs.append(_article_spec(
            title=title, slug=f"workflow-{slug}", category=category, roles=roles,
            summary=summary, routes=["help/workflows"], sources=sources,
            keywords=[title, "workflow", "approval", "handoff", "return"],
            steps=["Open the main Edify page and check the current status.", "Complete the action available to you and fill in the information it asks for.", "Check the notification or To-Do to see who needs to act next.", "If it is returned, fix the named problem on the same record and submit it again."],
            workflow=slug,
        ))
    for title, slug, category, roles, routes, sources, summary, first_step in FEATURES:
        specs.append(_article_spec(
            title=title, slug=f"feature-{slug}", category=category, roles=roles,
            summary=summary, routes=routes, sources=sources,
            keywords=[title, slug.replace("-", " "), "feature reference"],
            steps=[first_step, "Use the controls on this page and fix any message shown before you submit.", "Afterward, reopen or refresh the same record and check its status and who needs to act next."],
            feature=slug,
        ))
    for title, slug, correction in TROUBLESHOOTING:
        specs.append(_article_spec(
            title=title, slug=f"troubleshooting-{slug}", category="Troubleshooting",
            roles=["CCEO", "Program Lead", "CountryDirector", "ImpactAssessment", "RegionalVicePresident", "HumanResources", "Accountant", "PartnerAdmin", "PartnerFieldOfficer", "ProjectCoordinator", "Admin"],
            summary=correction, routes=["help/troubleshooting"],
            sources=["apps/frontend/views", "apps/core/permissions.py"],
            keywords=[title, slug.replace("-", " "), "error", "blocked", "fix"],
            steps=["Read the message or status shown on the record.", correction, "If someone else must fix it, use the named owner, notification or message without sharing private information."],
            feature="troubleshooting",
        ))
    specs.append(_article_spec(
        title="Workflow Status Reference", slug="glossary-workflow-statuses", category="Glossary",
        roles=["CCEO", "Program Lead", "CountryDirector", "ImpactAssessment", "RegionalVicePresident", "HumanResources", "Accountant", "PartnerAdmin", "PartnerFieldOfficer", "ProjectCoordinator", "Admin"],
        summary="The status reference is compiled from the choice fields that current models use for activity, evidence, verification, payment, advances and fund requests.",
        routes=["help/glossary"], sources=["apps/core/enums.py", "apps/activities/models.py", "apps/fund_requests/models.py"],
        keywords=["status", "awaiting", "returned", "verified", "approved", "closed"],
        steps=["Read the status on the source record.", "Use the related Contextual Help article for the enabled next action.", "Treat a returned state as correction work, not a completed result."], feature="status-reference",
    ))
    specs.append(_article_spec(
        title="Edify Identifiers: School, Salesforce, NetSuite and Finance References", slug="glossary-identifiers", category="Glossary",
        roles=["CCEO", "Program Lead", "CountryDirector", "ImpactAssessment", "RegionalVicePresident", "HumanResources", "Accountant", "PartnerAdmin", "PartnerFieldOfficer", "ProjectCoordinator", "Admin"],
        summary="Edify uses different identifiers for directory matching, Salesforce activity confirmation and financial traceability. They must never be substituted for one another.",
        routes=["help/glossary"], sources=["apps/schools/models.py", "apps/activities/models.py", "apps/fund_requests/models.py"],
        keywords=["school id", "sf id", "salesforce id", "netsuite id", "disbursement reference", "return reference"],
        steps=["Use School ID to match the structured SSA CSV row to the directory school.", "Enter a Salesforce Activity ID on the completed activity, using SVE- for visits and TS- for trainings.", "Enter a NetSuite Expense ID after accountability; the Accountant verifies it.", "Keep payment, return and reimbursement references on their original finance record."], feature="identifiers",
    ))
    return specs


@transaction.atomic
def ensure_canonical_content() -> dict:
    """Install v1 reviewed material once; never overwrite an editor's draft."""
    now = timezone.now()
    categories = {
        name: HelpCategory.objects.get_or_create(
            slug=slug,
            defaults={"name": name, "description": description, "sort_order": order},
        )[0]
        for name, slug, description, order in CATEGORIES
    }
    created = 0
    for spec in canonical_specs():
        article, was_created = HelpArticle.objects.get_or_create(
            slug=spec["slug"],
            defaults={
                "title": spec["title"], "summary": spec["summary"],
                "content": spec["content"], "category": categories[spec["category"]],
                "feature": spec["feature"], "workflow": spec["workflow"],
                "keywords": spec["keywords"], "source_paths": spec["sources"],
                "state": HelpArticleState.PUBLISHED,
                "version": 1,
                "reviewer_name": CANONICAL_REVIEWER,
                "last_reviewed_at": now,
                "published_at": now,
                "review_due_at": now + timedelta(days=REVIEW_INTERVAL_DAYS),
                "estimated_reading_minutes": max(
                    2, min(12, (len(str(spec["content"])) + len(spec["summary"])) // 500 + 2)
                ),
            },
        )
        if not was_created:
            continue
        created += 1
        article.rebuild_search_document(save=True)
        HelpArticleRoleAccess.objects.bulk_create(
            [HelpArticleRoleAccess(article=article, role=role) for role in spec["roles"]],
            ignore_conflicts=True,
        )
        HelpSearchKeyword.objects.bulk_create(
            [HelpSearchKeyword(article=article, term=term) for term in spec["keywords"]],
            ignore_conflicts=True,
        )
        HelpArticleVersion.objects.create(
            article=article, version=1, state=HelpArticleState.PUBLISHED,
            snapshot=article_snapshot(article), change_summary="Initial canonical-service reviewed publication.",
            reviewer_name=CANONICAL_REVIEWER, reviewed_at=now,
        )
    _seed_glossary()
    _seed_release_note()
    _seed_walkthroughs()
    return {"created": created, "articles": HelpArticle.objects.count()}


def _seed_glossary() -> None:
    status_article = HelpArticle.objects.filter(slug="glossary-workflow-statuses").first()
    identifiers = HelpArticle.objects.filter(slug="glossary-identifiers").first()
    for term, definition, used_in, related in GLOSSARY:
        HelpGlossaryTerm.objects.get_or_create(
            slug=slugify(term),
            defaults={
                "term": term, "definition": definition, "used_in": used_in,
                "related_terms": related, "article": identifiers if "ID" in term or "Reference" in term else status_article,
            },
        )
    for source, field_name, value, label in collect_workflow_statuses():
        term = label
        unique_slug = f"status-{slugify(source)}-{slugify(field_name)}-{slugify(value)}"
        HelpGlossaryTerm.objects.get_or_create(
            term=term,
            defaults={
                "slug": unique_slug,
                "term": term,
                "definition": f"{label} is the current {field_name.replace('_', ' ')} value defined by {source}. Open the source record to see the permitted next action.",
                "used_in": "Workflow status",
                "related_terms": [value, source],
                "article": status_article,
            },
        )


def _seed_release_note() -> None:
    HelpReleaseNote.objects.get_or_create(
        version_label="Knowledge Center 1.0",
        defaults={
            "title": "Authoritative in-product Knowledge Center",
            "summary": "Introduced role-aware help, contextual route help, controlled article versions, feedback, print/manual export and documentation drift checks.",
        },
    )


def _seed_walkthroughs() -> None:
    walkthroughs = [
        ("Schedule a School Visit", "schedule-school-visit", "feature-planning", "planning", ["Choose a school and delivery details.", "Resolve route, date and Cost Catalogue blockers.", "Confirm the saved activity in My Plan."]),
        ("Upload Evidence", "upload-evidence", "workflow-evidence-upload", "evidence", ["Open the assigned activity.", "Upload an accepted evidence file.", "Inspect the preview and submit for review."]),
        ("Enter Salesforce ID", "enter-salesforce-id", "feature-salesforce-activity-ids", "my-plan", ["Open the completed activity.", "Enter the correctly prefixed unique ID.", "Confirm the next IA status."]),
        ("Complete Accountability", "complete-accountability", "feature-accountability-returns-reimbursements", "accounts/accountability/", ["Enter real spend and receipt information.", "Explain variance.", "Submit the NetSuite reference when ready."]),
        ("Review Evidence as IA", "review-evidence-ia", "feature-ia-verification", "ia/verification/", ["Open a record awaiting IA.", "Complete each checklist check.", "Clear or return with reasons."]),
        ("Set a Cost Catalogue Rate", "set-cost-catalogue-rate", "feature-cost-catalogue", "cost-settings", ["Confirm the cost item and effective date.", "Enter whole-UGX rate.", "Save before planners create new activities."]),
    ]
    for title, slug, article_slug, route, steps in walkthroughs:
        article = HelpArticle.objects.filter(slug=article_slug).first()
        if article:
            HelpWalkthrough.objects.get_or_create(
                slug=slug,
                defaults={"title": title, "article": article, "route_pattern": route, "steps": steps, "roles": []},
            )


def visible_articles(role: str | None):
    queryset = HelpArticle.objects.filter(state__in=[HelpArticleState.PUBLISHED, HelpArticleState.REVIEW_DUE]).select_related("category", "reviewer").prefetch_related("role_accesses", "related_articles")
    if role:
        queryset = queryset.filter(Q(role_accesses__role=role) | ~Q(role_accesses__isnull=False)).distinct()
    return queryset


def article_for_slug(slug: str, role: str | None) -> HelpArticle | None:
    return visible_articles(role).filter(slug=slug).first()


def slug_for_role(role: str) -> str:
    return "role-" + slugify(role)


def personalized_articles(role: str, limit: int = 6):
    articles = visible_articles(role)
    priorities_by_role = {
        "CCEO": ["feature-planning", "feature-my-plan", "feature-ssa-comparison-recommendations", "workflow-evidence-upload", "feature-salesforce-activity-ids", "feature-accountability-returns-reimbursements"],
        "ImpactAssessment": ["feature-ia-verification", "feature-evidence-pdf-viewer", "feature-ssa-upload-history", "feature-unmatched-ssa", "workflow-ia-clear-return"],
        "Accountant": ["feature-disbursement", "feature-accountability-returns-reimbursements", "workflow-netsuite-verification", "feature-partner-payments", "feature-completed-activities"],
        "Program Lead": ["feature-my-plan", "feature-targets", "workflow-cceo-fund-approval", "workflow-catch-up-plans", "feature-field-debrief-leadership-actions"],
        "CountryDirector": ["feature-cost-catalogue", "feature-monthly-annual-budgets", "workflow-country-budget-rvp", "feature-analytics-reports", "feature-field-debrief-leadership-actions"],
        "RegionalVicePresident": ["workflow-country-budget-rvp", "feature-monthly-annual-budgets", "feature-analytics-reports", "workflow-debrief-leadership-action"],
        "HumanResources": ["feature-leave-temporary-coverage-feature", "feature-professional-development-feature", "feature-performance-reviews", "workflow-performance-review"],
        "PartnerAdmin": ["feature-partners", "workflow-partner-activity-execution", "workflow-evidence-upload", "feature-salesforce-activity-ids", "feature-partner-payments"],
        "PartnerFieldOfficer": ["feature-partners", "workflow-partner-activity-execution", "workflow-evidence-upload", "feature-salesforce-activity-ids", "feature-partner-payments"],
        "ProjectCoordinator": ["feature-special-projects", "feature-my-plan", "workflow-special-project-planning", "workflow-evidence-upload", "feature-targets"],
        "Admin": ["feature-user-management", "feature-roles-permissions", "feature-system-health-audit-log", "feature-authentication", "workflow-admin-user-onboarding"],
    }
    priorities = [f"role-{slugify(role)}", *priorities_by_role.get(role, ["getting-started"])]
    found = [article for slug in priorities if (article := articles.filter(slug=slug).first())]
    seen = {article.id for article in found}
    return (found + list(articles.exclude(id__in=seen).order_by("-last_reviewed_at")[:limit]))[:limit]


def expand_query(query: str) -> list[str]:
    clean = " ".join(query.lower().split())
    return list(dict.fromkeys([clean, SYNONYMS.get(clean, clean)]))


def search_articles(query: str, role: str | None):
    terms = expand_query(query)
    filters = Q()
    for term in terms:
        filters |= Q(title__icontains=term) | Q(summary__icontains=term) | Q(search_document__icontains=term) | Q(search_keywords__term__icontains=term)
    return visible_articles(role).filter(filters).distinct() if query.strip() else visible_articles(role).none()


def result_match_reason(article: HelpArticle, query: str) -> str:
    q = expand_query(query)[-1].lower()
    if q in article.title.lower():
        return "Matched article title"
    if q in " ".join(article.keywords or []).lower():
        return "Matched keyword or synonym"
    if q in article.summary.lower():
        return "Matched article summary"
    return "Matched verified instructions"


def excerpt(article: HelpArticle, query: str, limit: int = 180) -> str:
    text = article.search_document or article.rebuild_search_document(save=False)
    lower = text.lower()
    terms = expand_query(query)
    start = min((lower.find(term) for term in terms if lower.find(term) >= 0), default=0)
    beginning = max(0, start - 52)
    ending = min(len(text), beginning + limit)
    return ("…" if beginning else "") + text[beginning:ending].replace("\n", " ").strip() + ("…" if ending < len(text) else "")


def _route_inventory() -> list[tuple[str, str]]:
    from apps.frontend.urls import urlpatterns

    inventory = []
    for pattern in urlpatterns:
        if isinstance(pattern, URLPattern):
            route = str(pattern.pattern)
            if route:
                inventory.append((route, pattern.name or ""))
    return inventory


ROUTE_PREFIX_ARTICLES = [
    ("help", "getting-started"), ("schools", "feature-school-directory"),
    ("clusters", "feature-clusters"), ("ssa", "feature-ssa-upload-history"),
    ("core-schools", "feature-core-schools"), ("planning", "feature-planning"),
    ("my-plan", "feature-my-plan"), ("calendar", "feature-routes-daily-visit-batches"),
    ("fund", "feature-weekly-fund-requests"), ("budget", "feature-monthly-annual-budgets"),
    ("cost-settings", "feature-cost-catalogue"), ("disbursements", "feature-disbursement"),
    ("accounts", "feature-accountability-returns-reimbursements"), ("activities/closure", "feature-completed-activities"),
    ("evidence", "feature-evidence-pdf-viewer"), ("ia", "feature-ia-verification"),
    ("partner", "feature-partners"), ("projects", "feature-special-projects"),
    ("targets", "feature-targets"), ("analytics", "feature-analytics-reports"),
    ("reports", "feature-analytics-reports"), ("debriefs", "feature-field-debrief-leadership-actions"),
    ("leave", "feature-leave-temporary-coverage-feature"), ("professional", "feature-professional-development-feature"),
    ("performance", "feature-performance-reviews"), ("admin", "feature-system-health-audit-log"),
    ("system", "feature-system-health-audit-log"), ("messages", "feature-messages"),
    ("notifications", "feature-notifications"), ("todos", "feature-todos"), ("login", "feature-authentication"),
]


def _article_slug_for_route(route: str, name: str) -> str:
    direct = {route_name: slug for spec in canonical_specs() for route_name in spec["routes"] for slug in [spec["slug"]]}
    if name in direct:
        return direct[name]
    for prefix, slug in ROUTE_PREFIX_ARTICLES:
        if route.startswith(prefix):
            return slug
    return "getting-started"


@transaction.atomic
def sync_route_contexts() -> dict:
    ensure_canonical_content()
    created = 0
    for route, name in _route_inventory():
        slug = _article_slug_for_route(route, name)
        article = HelpArticle.objects.filter(slug=slug).first()
        if not article:
            continue
        _, was_created = HelpArticleRouteContext.objects.get_or_create(
            article=article, route_pattern=route, workflow_status="",
            defaults={"route_name": name, "priority": 100},
        )
        created += int(was_created)
    return {"created": created, "mapped": HelpArticleRouteContext.objects.values("route_pattern").distinct().count()}


def contextual_article(path: str, role: str | None, workflow_status: str = "") -> HelpArticle | None:
    ensure_canonical_content()
    try:
        match = resolve(path.split("?", 1)[0])
        route = match.route
    except Exception:
        route = path.strip("/")
    contexts = HelpArticleRouteContext.objects.filter(route_pattern=route).select_related("article")
    if not contexts.exists():
        sync_route_contexts()
        contexts = HelpArticleRouteContext.objects.filter(route_pattern=route).select_related("article")
    if workflow_status:
        contexts = contexts.filter(Q(workflow_status=workflow_status) | Q(workflow_status=""))
    for context in contexts.order_by("priority"):
        if article_for_slug(context.article.slug, role):
            return context.article
    return article_for_slug("getting-started", role)


def record_feedback(*, article: HelpArticle, user, helpful: bool | None, feedback_type: str, comment: str, page_context: str) -> HelpArticleFeedback:
    return HelpArticleFeedback.objects.create(
        article=article, user=user if getattr(user, "is_authenticated", False) else None,
        user_role=getattr(user, "active_role", ""), helpful=helpful,
        feedback_type=feedback_type, comment=(comment or "").strip(), page_context=(page_context or "")[:255],
    )


TRANSITIONS = {
    HelpArticleState.DRAFT: {"submit": HelpArticleState.TECHNICAL_REVIEW},
    HelpArticleState.TECHNICAL_REVIEW: {"technical_review": HelpArticleState.PRODUCT_REVIEW, "return": HelpArticleState.DRAFT},
    HelpArticleState.PRODUCT_REVIEW: {"product_review": HelpArticleState.APPROVED, "return": HelpArticleState.DRAFT},
    HelpArticleState.APPROVED: {"publish": HelpArticleState.PUBLISHED, "return": HelpArticleState.DRAFT},
    HelpArticleState.PUBLISHED: {"archive": HelpArticleState.ARCHIVED, "review_due": HelpArticleState.REVIEW_DUE},
    HelpArticleState.REVIEW_DUE: {"publish": HelpArticleState.PUBLISHED, "archive": HelpArticleState.ARCHIVED},
}


@transaction.atomic
def transition_article(article: HelpArticle, action: str, actor, *, change_summary: str = "") -> HelpArticle:
    next_state = TRANSITIONS.get(article.state, {}).get(action)
    if not next_state:
        raise ValueError(f"Cannot {action.replace('_', ' ')} an article in {article.get_state_display().lower()}.")
    now = timezone.now()
    article.state = next_state
    if action in {"technical_review", "product_review", "publish"}:
        article.reviewer = actor
        article.reviewer_name = getattr(actor, "name", "") or getattr(actor, "email", "")
        article.last_reviewed_at = now
    version_number = (article.versions.aggregate(latest=Max("version"))["latest"] or 0) + 1
    if action == "publish":
        article.published_at = now
        article.review_due_at = now + timedelta(days=REVIEW_INTERVAL_DAYS)
        article.version = version_number
    article.full_clean()
    article.save()
    article.rebuild_search_document(save=True)
    HelpArticleVersion.objects.create(
        article=article, version=version_number, state=article.state,
        snapshot=article_snapshot(article), change_summary=change_summary or action.replace("_", " ").capitalize(),
        author=article.author, reviewer=article.reviewer, reviewer_name=article.reviewer_name,
        reviewed_at=article.last_reviewed_at,
    )
    return article


@transaction.atomic
def create_revision(article: HelpArticle, author) -> HelpArticle:
    """Make a separate draft from a publication without mutating live help."""
    base = f"{article.slug}-revision"
    counter = 1
    slug = f"{base}-{counter}"
    while HelpArticle.objects.filter(slug=slug).exists():
        counter += 1
        slug = f"{base}-{counter}"
    revision = HelpArticle.objects.create(
        title=f"{article.title} (revision)", slug=slug, summary=article.summary,
        content=article.content, search_document=article.search_document,
        category=article.category, feature=article.feature, workflow=article.workflow,
        keywords=article.keywords, source_paths=article.source_paths,
        state=HelpArticleState.DRAFT, author=author,
        estimated_reading_minutes=article.estimated_reading_minutes,
    )
    HelpArticleRoleAccess.objects.bulk_create(
        [HelpArticleRoleAccess(article=revision, role=role) for role in article.role_accesses.values_list("role", flat=True)]
    )
    HelpArticleRouteContext.objects.bulk_create(
        [HelpArticleRouteContext(article=revision, route_pattern=context.route_pattern, route_name=context.route_name, workflow_status=context.workflow_status, priority=context.priority)
         for context in article.route_contexts.all()]
    )
    return revision


def mark_review_due_articles() -> int:
    return HelpArticle.objects.filter(
        state=HelpArticleState.PUBLISHED, review_due_at__lt=timezone.now()
    ).update(state=HelpArticleState.REVIEW_DUE)


def collect_workflow_statuses() -> list[tuple[str, str, str, str]]:
    """Read current Django choices so the drift check is model-led, not prose-led."""
    model_fields = [
        ("Activity", "apps.activities.models", "Activity", ["status", "evidence_status", "ia_verification_status", "payment_status"]),
        ("Fund request", "apps.fund_requests.models", "FundRequest", ["status"]),
        ("Advance request", "apps.fund_requests.models", "AdvanceRequest", ["status"]),
        ("Professional development", "apps.professional_development.models", "ProfessionalDevelopmentRequest", ["status"]),
        ("Leave", "apps.hr.models", "Leave", ["status"]),
    ]
    result = []
    for source, module_path, model_name, fields in model_fields:
        try:
            module = __import__(module_path, fromlist=[model_name])
            model = getattr(module, model_name)
        except (ImportError, AttributeError):
            continue
        for field_name in fields:
            try:
                choices = model._meta.get_field(field_name).choices
            except Exception:
                continue
            for value, label in choices or []:
                result.append((source, field_name, str(value), str(label)))
    return result


def documentation_drift_report() -> dict:
    ensure_canonical_content()
    inventory = _route_inventory()
    mapped = set(HelpArticleRouteContext.objects.values_list("route_pattern", flat=True))
    missing_routes = [{"route": route, "name": name} for route, name in inventory if route not in mapped]
    # A manually curated glossary definition may cover a status before the
    # automatic choice-field seeder sees it; both are valid documentation.
    known_statuses = set(HelpGlossaryTerm.objects.values_list("term", flat=True))
    unknown_statuses = [
        {"source": source, "field": field, "value": value, "label": label}
        for source, field, value, label in collect_workflow_statuses() if label not in known_statuses
    ]
    broken_related = []
    for article in HelpArticle.objects.prefetch_related("related_articles"):
        if article.is_published and article.category_id is None:
            broken_related.append({"article": article.slug, "issue": "published article missing category"})
    overdue = list(HelpArticle.objects.filter(
        state__in=[HelpArticleState.PUBLISHED, HelpArticleState.REVIEW_DUE],
        review_due_at__lt=timezone.now(),
    ).values_list("slug", flat=True))
    published = HelpArticle.objects.filter(state__in=[HelpArticleState.PUBLISHED, HelpArticleState.REVIEW_DUE])
    no_version = [slug for slug in published.exclude(versions__isnull=False).values_list("slug", flat=True)]
    coverage = round(100 * (len(inventory) - len(missing_routes)) / len(inventory), 1) if inventory else 100.0
    return {
        "coverage_percent": coverage,
        "route_count": len(inventory),
        "mapped_routes": len(inventory) - len(missing_routes),
        "missing_routes": missing_routes,
        "unknown_statuses": unknown_statuses,
        "broken_links": broken_related,
        "overdue_articles": overdue,
        "published_without_version": no_version,
        "published_articles": published.count(),
        "role_guides": HelpArticle.objects.filter(feature="role-guide").count(),
        "workflow_guides": HelpArticle.objects.exclude(workflow="").count(),
        "troubleshooting_articles": HelpArticle.objects.filter(feature="troubleshooting").count(),
        "glossary_terms": HelpGlossaryTerm.objects.count(),
        "walkthroughs": HelpWalkthrough.objects.filter(active=True).count(),
    }
