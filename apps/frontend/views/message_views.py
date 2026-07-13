"""Messages center — contextual, workflow-linked communication.

Three-panel inbox (threads / conversation / workflow context) plus a
context-first compose flow. All partial updates go through HTMX; Alpine
only handles local UI state.
"""

from django.contrib import messages as django_messages
from django.http import HttpResponse
from django.shortcuts import redirect, render

from apps.core.exceptions import BadRequest, Forbidden, NotFoundError
from apps.core.permissions import require_page_permission
from apps.messaging import services
from apps.messaging.models import (
    Message,
    MessageAttachment,
    MessageDraft,
    MessageThread,
)

TABS = [
    ("all", "All"),
    ("unread", "Unread"),
    ("assigned", "Assigned to Me"),
    ("sent", "Sent"),
    ("archived", "Archived"),
    ("partner", "Partner"),
    ("finance", "Finance"),
    ("ia_review", "IA Review"),
]


def _thread_context(request, thread_id):
    """Conversation + workflow context panel data for a thread, or None."""
    if not thread_id:
        return None
    try:
        detail = services.thread_detail(thread_id, request.user)
    except (NotFoundError, Forbidden):
        return None
    t = detail["thread"]
    panel = services.context_panel(t, request.user)
    suggestions = services.suggested_recipients(
        request.user, t.context_type, t.context_id
    )
    in_thread = {p["id"] for p in detail["participants"]}
    linked_ids = [i["id"] for i in (t.linked_items or [])]
    try:
        summary = services.context_summary(
            request.user, t.context_type, t.context_id, linked_ids
        )
    except Exception:
        summary = None
    return {
        **detail,
        "panel": panel,
        "context_suggestions": [s for s in suggestions if s["id"] not in in_thread],
        "summary": summary,
    }


PAGE_SIZE = 8

MESSAGE_RULES = [
    "Context required for all new messages",
    "Replies inherit context automatically",
    "Only registered users can be selected",
    "Suggested recipients are based on context and geography",
    "You cannot message about records you cannot access",
    "Workflow decisions must still use workflow actions",
]


@require_page_permission("messages")
def messages_list_view(request):
    tab = request.GET.get("tab", "all")
    q = request.GET.get("q", "").strip()
    sort = request.GET.get("sort", "newest")
    try:
        page = max(1, int(request.GET.get("page", 1)))
    except ValueError:
        page = 1

    threads = services.threads_for_user(request.user, tab=tab, search=q)
    if sort == "oldest":
        threads = list(reversed(threads))
    total = len(threads)
    pages = max(1, -(-total // PAGE_SIZE))
    page = min(page, pages)
    start = (page - 1) * PAGE_SIZE
    page_threads = threads[start : start + PAGE_SIZE]

    tab_counts = {
        "all": total
        if tab == "all" and not q
        else len(services.threads_for_user(request.user, tab="all")),
        "unread": len(services.threads_for_user(request.user, tab="unread")),
        "assigned": len(services.threads_for_user(request.user, tab="assigned")),
    }

    selected_id = request.GET.get("thread") or (
        page_threads[0]["id"] if page_threads else None
    )
    selected = _thread_context(request, selected_id)

    context = {
        "tabs": TABS,
        "active_tab": tab,
        "tab_counts": tab_counts,
        "search_q": q,
        "sort": sort,
        "threads": page_threads,
        "page": page,
        "pages": pages,
        "total": total,
        "showing_start": (start + 1) if total else 0,
        "showing_end": min(start + PAGE_SIZE, total),
        "page_range": range(1, pages + 1),
        "selected": selected,
        "selected_id": selected["thread"].id if selected else None,
        # Compose popup data
        "categories": services.categories_for_role(request.user),
        "recipients": services.recipients(request.user),
        "context_tabs": services.CONTEXT_TABS,
        "message_rules": MESSAGE_RULES,
    }
    if request.headers.get("HX-Request") == "true":
        return render(request, "partials/messages/thread_list.html", context)
    return render(request, "pages/messages/index.html", context)


@require_page_permission("messages")
def thread_view(request, thread_id):
    """Conversation partial (HTMX) or the full page focused on the thread."""
    if request.headers.get("HX-Request") != "true":
        return redirect(f"/messages?thread={thread_id}")
    selected = _thread_context(request, thread_id)
    if not selected:
        return HttpResponse(
            '<div class="p-8 text-center text-[12px] font-semibold text-slate-400">'
            "This conversation is unavailable or you no longer have access to its record."
            "</div>",
            status=200,
        )
    return render(
        request,
        "partials/messages/conversation.html",
        {"selected": selected, "selected_id": thread_id, "oob_context": True},
    )


@require_page_permission("messages")
def thread_reply_action(request, thread_id):
    if request.method != "POST":
        return redirect(f"/messages?thread={thread_id}")
    body = request.POST.get("body", "").strip()
    if body:
        try:
            msg = services.reply(thread_id, {"body": body}, request.user)
            for f in request.FILES.getlist("attachments"):
                MessageAttachment.objects.create(
                    message_id=msg["id"],
                    file=f,
                    file_name=f.name,
                    file_type=f.content_type or "",
                    file_size=f.size or 0,
                    uploaded_by=request.user.id,
                )
        except (Forbidden, NotFoundError, BadRequest) as e:
            django_messages.error(request, f"Could not send reply: {e}")
    selected = _thread_context(request, thread_id)
    if request.headers.get("HX-Request") == "true":
        return render(
            request,
            "partials/messages/conversation.html",
            {"selected": selected, "selected_id": thread_id, "oob_context": True},
        )
    return redirect(f"/messages?thread={thread_id}")


@require_page_permission("messages")
def thread_archive_action(request, thread_id):
    if request.method == "POST":
        try:
            unarchive = request.POST.get("unarchive") == "1"
            services.archive_thread(thread_id, request.user, archived=not unarchive)
        except (Forbidden, NotFoundError):
            pass
    resp = HttpResponse(status=204)
    resp["HX-Redirect"] = "/messages"
    return resp


@require_page_permission("messages")
def thread_star_action(request, thread_id):
    starred = False
    if request.method == "POST":
        try:
            starred = services.toggle_star(thread_id, request.user)["starred"]
        except (Forbidden, NotFoundError):
            pass
    icon = "★" if starred else "☆"
    tone = "text-amber-400" if starred else "text-slate-300"
    return HttpResponse(
        f'<button hx-post="/messages/thread/{thread_id}/star" hx-swap="outerHTML" '
        f'class="text-[18px] {tone} hover:text-amber-400 transition-colors" '
        f'aria-label="Star conversation">{icon}</button>'
    )


@require_page_permission("messages")
def message_deep_link_view(request, message_id):
    """Legacy deep link (/messages/<message_id>) used by notifications."""
    msg = Message.objects.filter(id=message_id).first()
    if msg:
        return redirect(f"/messages?thread={msg.thread_id}")
    if MessageThread.objects.filter(id=message_id).exists():
        return redirect(f"/messages?thread={message_id}")
    django_messages.error(request, "That conversation could not be found.")
    return redirect("/messages")


# ── Compose ──────────────────────────────────────────────────────────────────


def _compose_context(request, *, draft=None, forward_thread=None):
    ctx_type = request.GET.get("context_type", "")
    ctx_id = request.GET.get("context_id", "")
    subject = ""
    body = ""
    category = ""
    if draft:
        ctx_type = draft.context_type or ctx_type
        ctx_id = draft.context_id or ctx_id
        subject, body, category = draft.subject, draft.body, draft.category or ""
    if forward_thread:
        ctx_type = forward_thread.context_type or ctx_type
        ctx_id = forward_thread.context_id or ctx_id
        subject = f"Fwd: {forward_thread.subject}"
        first = forward_thread.messages.order_by("created_at").first()
        if first:
            body = f"\n\n--- Forwarded message ---\n{first.body}"

    # Normalise picker tab: activity-family contexts land on the activity tab.
    # With no pre-selected context the picker opens on Schedule (the default
    # in the approved design).
    active_tab = (
        ctx_type
        if ctx_type in dict(services.CONTEXT_TABS)
        else (
            "activity"
            if ctx_type in services.ACTIVITY_CONTEXTS
            else (ctx_type or "schedule")
        )
    )
    if active_tab not in dict(services.CONTEXT_TABS):
        active_tab = "schedule"

    context_label = ""
    suggestions = []
    if ctx_type and ctx_id:
        context_label = services.resolve_context_label(ctx_type, ctx_id)
        suggestions = services.suggested_recipients(request.user, ctx_type, ctx_id)

    # Resolve draft/forward recipients to chip data for the Alpine state.
    pre_to, pre_cc = [], []
    if draft:
        from apps.accounts.models import User

        users = {
            u.id: u
            for u in User.objects.filter(id__in=[*draft.recipient_ids, *draft.cc_ids])
        }
        pre_to = [
            {"id": u.id, "name": u.name, "role": u.active_role or ""}
            for rid in draft.recipient_ids
            if (u := users.get(rid))
        ]
        pre_cc = [
            {"id": u.id, "name": u.name, "role": u.active_role or ""}
            for rid in draft.cc_ids
            if (u := users.get(rid))
        ]

    import json

    return {
        "pre_to": pre_to,
        "pre_cc": pre_cc,
        "context_type_labels_json": json.dumps(services.CONTEXT_LABELS),
        "context_tabs": services.CONTEXT_TABS,
        "active_context_tab": active_tab,
        "pre_context_type": ctx_type,
        "pre_context_id": ctx_id,
        "pre_context_label": context_label,
        "pre_subject": subject,
        "pre_body": body,
        "pre_category": category,
        "categories": services.categories_for_role(request.user),
        "recipients": services.recipients(request.user),
        "suggested": suggestions,
        "draft": draft,
        "drafts": services.drafts_for_user(request.user),
        "records": services.search_context_records(request.user, active_tab, ""),
    }


@require_page_permission("messages")
def message_compose_view(request):
    if request.method == "POST":
        data = {
            "recipientIds": request.POST.getlist("recipient_ids"),
            "ccIds": request.POST.getlist("cc_ids"),
            "subject": request.POST.get("subject", "").strip(),
            "category": request.POST.get("category") or None,
            "contextType": request.POST.get("context_type"),
            "contextId": request.POST.get("context_id"),
            "linkedItems": request.POST.getlist("linked_ids"),
            "body": request.POST.get("body", "").strip(),
        }
        if request.POST.get("action") == "draft":
            services.save_draft(
                {**data, "draftId": request.POST.get("draft_id")}, request.user
            )
            django_messages.success(request, "Draft saved.")
            return redirect("/messages/new/")
        try:
            if not data["subject"] or not data["body"]:
                raise BadRequest("Subject and message are required.")
            msg = services.send(data, request.user)
            for f in request.FILES.getlist("attachments"):
                MessageAttachment.objects.create(
                    message_id=msg["id"],
                    file=f,
                    file_name=f.name,
                    file_type=f.content_type or "",
                    file_size=f.size or 0,
                    uploaded_by=request.user.id,
                )
            if request.POST.get("draft_id"):
                MessageDraft.objects.filter(
                    id=request.POST["draft_id"], user_id=request.user.id
                ).delete()
            django_messages.success(request, "Message sent.")
            return redirect(f"/messages?thread={msg['threadId']}")
        except (BadRequest, Forbidden, NotFoundError) as e:
            django_messages.error(request, f"Could not send message: {e}")

    draft = None
    if request.GET.get("draft"):
        draft = MessageDraft.objects.filter(
            id=request.GET["draft"], user_id=request.user.id
        ).first()
    forward_thread = None
    if request.GET.get("forward"):
        try:
            forward_thread = services._require_thread_access(
                request.GET["forward"], request.user
            )
        except (Forbidden, NotFoundError):
            forward_thread = None
    context = _compose_context(request, draft=draft, forward_thread=forward_thread)
    return render(request, "pages/messages/new.html", context)


@require_page_permission("messages")
def compose_records_partial(request):
    ctx_type = request.GET.get("type", "school")
    q = request.GET.get("q", "")
    status_filter = request.GET.get("status", "")
    variant = request.GET.get("variant", "")
    target = request.GET.get("target", "")
    records = services.search_context_records(request.user, ctx_type, q, status_filter)
    return render(
        request,
        "partials/messages/context_records.html",
        {
            "records": records,
            "context_tab": ctx_type,
            "variant": variant,
            "target": target,
        },
    )


@require_page_permission("messages")
def compose_suggestions_partial(request):
    ctx_type = request.GET.get("type", "")
    ctx_id = request.GET.get("id", "")
    label = services.resolve_context_label(ctx_type, ctx_id) if ctx_id else ""
    allowed = services.can_access_context(request.user, ctx_type, ctx_id)
    suggestions = (
        services.suggested_recipients(request.user, ctx_type, ctx_id) if allowed else []
    )
    return render(
        request,
        "partials/messages/recipient_suggestions.html",
        {
            "suggested": suggestions,
            "context_label": label,
            "context_type_label": services.CONTEXT_LABELS.get(ctx_type, ctx_type),
            "context_allowed": allowed,
            "context_type": ctx_type,
            "context_id": ctx_id,
            "compact": request.GET.get("compact", ""),
        },
    )


@require_page_permission("messages")
def compose_summary_partial(request):
    ctx_type = request.GET.get("type", "")
    ctx_id = request.GET.get("id", "")
    linked = [i for i in request.GET.get("linked", "").split(",") if i]
    allowed = services.can_access_context(request.user, ctx_type, ctx_id)
    summary = (
        services.context_summary(request.user, ctx_type, ctx_id, linked)
        if (ctx_id and allowed)
        else None
    )
    return render(
        request,
        "partials/messages/context_summary.html",
        {"summary": summary, "context_allowed": allowed, "has_context": bool(ctx_id)},
    )
