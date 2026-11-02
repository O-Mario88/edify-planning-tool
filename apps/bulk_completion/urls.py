from django.urls import path

from apps.bulk_completion import views

urlpatterns = [
    path(
        "uploads/bulk-completion/batch/<str:batch_id>",
        views.batch_view,
        name="bulk_completion_batch",
    ),
    path(
        "uploads/bulk-completion/batch/<str:batch_id>/confirm",
        views.confirm_view,
        name="bulk_completion_confirm",
    ),
    path(
        "uploads/bulk-completion/batch/<str:batch_id>/cancel",
        views.cancel_view,
        name="bulk_completion_cancel",
    ),
    path(
        "uploads/bulk-completion/batch/<str:batch_id>/report",
        views.error_report_view,
        name="bulk_completion_report",
    ),
    path(
        "uploads/bulk-completion/<str:kind>",
        views.upload_view,
        name="bulk_completion_upload",
    ),
    path(
        "uploads/bulk-completion/<str:kind>/template",
        views.template_view,
        name="bulk_completion_template",
    ),
]
