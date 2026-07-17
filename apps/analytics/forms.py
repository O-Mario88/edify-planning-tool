from django import forms

from .models import AnalyticsDashboardPreference, AnalyticsReportSchedule
from .report_delivery import ALLOWED_CATEGORIES


class AnalyticsReportScheduleForm(forms.ModelForm):
    categories = forms.MultipleChoiceField(
        choices=[
            ("targets", "Target achievement"),
            ("training", "Training reach"),
            ("reach", "Schools and students reached"),
            ("ssa", "SSA performance"),
        ],
        widget=forms.CheckboxSelectMultiple,
    )

    class Meta:
        model = AnalyticsReportSchedule
        fields = ["frequency", "categories"]

    def clean_categories(self):
        values = list(dict.fromkeys(self.cleaned_data["categories"]))
        if not values or not set(values).issubset(ALLOWED_CATEGORIES):
            raise forms.ValidationError("Choose at least one valid analytics category.")
        return values


class AnalyticsInboxSnapshotForm(forms.Form):
    """Validate an immediate, user-triggered in-app analytics delivery."""

    categories = forms.MultipleChoiceField(
        choices=[
            ("targets", "Target achievement"),
            ("training", "Training reach"),
            ("reach", "Schools and students reached"),
            ("ssa", "SSA performance"),
        ],
        widget=forms.CheckboxSelectMultiple,
    )

    def clean_categories(self):
        values = list(dict.fromkeys(self.cleaned_data["categories"]))
        if not values or not set(values).issubset(ALLOWED_CATEGORIES):
            raise forms.ValidationError("Choose at least one valid analytics category.")
        return values


class AnalyticsDashboardPreferenceForm(forms.ModelForm):
    visible_cards = forms.MultipleChoiceField(
        choices=[
            ("targets", "Overall target achievement"),
            ("training", "Teachers and leaders trained"),
            ("reach", "Students and schools impacted"),
            ("ssa", "SSA average performance"),
        ],
        widget=forms.CheckboxSelectMultiple,
    )

    class Meta:
        model = AnalyticsDashboardPreference
        fields = ["visible_cards", "layout"]

    def clean_visible_cards(self):
        values = list(dict.fromkeys(self.cleaned_data["visible_cards"]))
        if not values:
            raise forms.ValidationError("Keep at least one KPI group visible.")
        return values


__all__ = [
    "AnalyticsDashboardPreferenceForm",
    "AnalyticsInboxSnapshotForm",
    "AnalyticsReportScheduleForm",
]
