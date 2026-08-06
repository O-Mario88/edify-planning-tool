from django.urls import path

from . import views


urlpatterns = [
    path("search", views.search, name="help_search"),
    path(
        "getting-started",
        views.article,
        {"slug": "getting-started"},
        name="help_getting_started",
    ),
    path("roles/<slug:role_slug>", views.role_guide, name="help_role"),
    path("workflows/<slug:workflow_slug>", views.workflow, name="help_workflow"),
    path("features/<slug:feature_slug>", views.feature, name="help_feature"),
    path("articles/<slug:slug>/print", views.print_article, name="help_print"),
    path("articles/<slug:slug>/feedback", views.feedback, name="help_feedback"),
    path("articles/<slug:slug>", views.article, name="help_article"),
    path("categories/<slug:slug>", views.category, name="help_category"),
    path("troubleshooting", views.troubleshooting, name="help_troubleshooting"),
    path("glossary", views.glossary, name="help_glossary"),
    path("release-notes", views.release_notes, name="help_release_notes"),
    path("context", views.contextual, name="help_context"),
    path(
        "export/role/<slug:role_slug>",
        views.role_manual_export,
        name="help_role_export",
    ),
    path("export/complete", views.complete_manual_export, name="help_complete_export"),
    path("manage", views.manage, name="help_manage"),
    path("manage/new", views.manage_article, name="help_manage_new"),
    path("manage/<slug:slug>", views.manage_article, name="help_manage_article"),
    path(
        "manage/<slug:slug>/revision",
        views.manage_revision,
        name="help_manage_revision",
    ),
    path(
        "manage/<slug:slug>/<slug:action>",
        views.manage_transition,
        name="help_manage_transition",
    ),
]
