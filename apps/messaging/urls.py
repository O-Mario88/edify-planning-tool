from django.urls import path

from . import views

urlpatterns = [
    path("", views.MessageListSendView.as_view(), name="list"),
    path("recent", views.MessageListSendView.as_view(), name="recent"),
    path("counts", views.MessageCountsView.as_view(), name="counts"),
    path("recipients", views.MessageRecipientsView.as_view(), name="recipients"),
    path("contexts", views.MessageContextsView.as_view(), name="contexts"),
    path("thread/<str:thread_id>", views.MessageThreadView.as_view(), name="thread"),
    path("<str:thread_id>/reply", views.MessageReplyView.as_view(), name="reply"),
    path("<str:message_id>/read", views.MessageReadView.as_view(), name="read"),
]
