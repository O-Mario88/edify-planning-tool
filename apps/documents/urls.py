"""Upload Center, Document Library and policy-agreement routes.

``/documents/…`` and ``/policy-agreement/…`` are exempt from the policy gate
(see apps/documents/gate.py) — a person being asked to accept a policy has to
be able to read it, download it, answer it and reach HR.
"""

from django.urls import path

from apps.documents import views

urlpatterns = [
    # Upload Center
    path("uploads", views.upload_center_view, name="upload_center"),
    path("uploads/new", views.new_document_view, name="new_document"),
    # Document Library
    path("documents/<slug:slug>/", views.document_viewer_view, name="document_viewer"),
    path(
        "documents/<slug:slug>/preview",
        views.document_preview_view,
        name="document_preview",
    ),
    path(
        "documents/<slug:slug>/download",
        views.document_download_view,
        name="document_download",
    ),
    path(
        "documents/<slug:slug>/print",
        views.document_print_view,
        name="document_print",
    ),
    path(
        "documents/<slug:slug>/manage",
        views.manage_document_view,
        name="manage_document",
    ),
    path(
        "documents/<slug:slug>/versions/new",
        views.new_version_view,
        name="new_document_version",
    ),
    path(
        "documents/<slug:slug>/<str:action>",
        views.document_action_view,
        name="document_action",
    ),
    path(
        "api/documents/engagement/<str:version_id>",
        views.engagement_heartbeat_view,
        name="document_engagement",
    ),
    # Policy Agreement Center
    path("policy-agreement", views.agreement_center_view, name="policy_agreement"),
    path(
        "policy-agreement/restricted", views.restricted_view, name="policy_restricted"
    ),
    path(
        "api/documents/acknowledge/<str:acknowledgement_id>",
        views.submit_acknowledgement_view,
        name="submit_acknowledgement",
    ),
    path(
        "api/documents/attest/<str:acknowledgement_id>",
        views.attest_offline_view,
        name="attest_offline",
    ),
    # Compliance reporting
    path("policy-compliance", views.compliance_view, name="policy_compliance"),
    path(
        "policy-compliance/comments/<str:comment_id>",
        views.respond_comment_view,
        name="respond_comment",
    ),
]
