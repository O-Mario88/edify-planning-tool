from django.contrib import admin

from .models import (
    HelpArticle, HelpArticleFeedback, HelpArticleRoleAccess, HelpArticleRouteContext,
    HelpArticleVersion, HelpCategory, HelpGlossaryTerm, HelpReleaseNote, HelpSearchKeyword,
    HelpWalkthrough,
)


class RoleAccessInline(admin.TabularInline):
    model = HelpArticleRoleAccess
    extra = 0


class RouteContextInline(admin.TabularInline):
    model = HelpArticleRouteContext
    extra = 0


class VersionInline(admin.TabularInline):
    model = HelpArticleVersion
    readonly_fields = ("version", "state", "snapshot", "change_summary", "reviewed_at")
    can_delete = False
    extra = 0


@admin.register(HelpArticle)
class HelpArticleAdmin(admin.ModelAdmin):
    list_display = ("title", "category", "state", "version", "last_reviewed_at", "review_due_at")
    list_filter = ("state", "category")
    search_fields = ("title", "summary", "search_document", "keywords")
    prepopulated_fields = {"slug": ("title",)}
    inlines = (RoleAccessInline, RouteContextInline, VersionInline)


admin.site.register(HelpCategory)
admin.site.register(HelpGlossaryTerm)
admin.site.register(HelpSearchKeyword)
admin.site.register(HelpArticleFeedback)
admin.site.register(HelpReleaseNote)
admin.site.register(HelpWalkthrough)
