from __future__ import annotations

from django import forms

from apps.core.rbac import EdifyRole

from .models import HelpArticle


class HelpArticleForm(forms.ModelForm):
    roles = forms.MultipleChoiceField(
        choices=[(role.value, role.value) for role in EdifyRole],
        required=False,
        widget=forms.CheckboxSelectMultiple,
        help_text="Leave empty only for a deliberately all-role article.",
    )
    route_patterns = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={"rows": 3}),
        help_text="One frontend route pattern per line, for example schools or my-plan/<str:activity_id>.",
    )

    class Meta:
        model = HelpArticle
        fields = ["title", "slug", "summary", "content", "category", "feature", "workflow", "keywords", "source_paths", "estimated_reading_minutes"]
        widgets = {
            "summary": forms.Textarea(attrs={"rows": 3}),
            "content": forms.Textarea(attrs={"rows": 14}),
            "keywords": forms.Textarea(attrs={"rows": 3}),
            "source_paths": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance and self.instance.pk:
            self.fields["roles"].initial = list(self.instance.role_accesses.values_list("role", flat=True))
            self.fields["route_patterns"].initial = "\n".join(self.instance.route_contexts.values_list("route_pattern", flat=True))

    def clean_content(self):
        content = self.cleaned_data["content"]
        if not isinstance(content, list) or not content:
            raise forms.ValidationError("Content must be a non-empty JSON list of article sections.")
        for section in content:
            if not isinstance(section, dict) or not section.get("heading"):
                raise forms.ValidationError("Each content section needs a heading.")
        return content
