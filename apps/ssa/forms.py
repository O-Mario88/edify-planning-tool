"""Server-rendered forms for manual SSA entry."""

from __future__ import annotations

from django import forms

from apps.core.enums import SsaIntervention


CONTROL_CLASS = (
    "w-full min-h-11 rounded-control border border-[var(--edify-border)] "
    "bg-[var(--edify-surface)] px-3 text-[16px] sm:text-[13px] font-semibold "
    "focus:outline-none focus:ring-4 edify-primary-focus edify-primary-focus"
)


class ManualSsaEntryForm(forms.Form):
    school_id = forms.CharField(
        label="School",
        max_length=64,
        widget=forms.TextInput(
            attrs={
                "class": CONTROL_CLASS,
                "list": "manual-ssa-school-options",
                "autocomplete": "off",
                "placeholder": "Type or select a School ID",
                "aria-describedby": "manual-ssa-school-help",
            }
        ),
    )
    date_of_ssa = forms.DateField(
        label="Assessment date",
        widget=forms.DateInput(
            attrs={
                "class": CONTROL_CLASS,
                "type": "date",
                "aria-describedby": "manual-ssa-date-help",
            }
        ),
    )

    def __init__(self, *args, school_queryset, **kwargs):
        super().__init__(*args, **kwargs)
        self.school_queryset = school_queryset
        self.school = None
        for code, label in SsaIntervention.choices:
            self.fields[f"score_{code}"] = forms.DecimalField(
                label=label,
                min_value=0,
                max_value=10,
                max_digits=3,
                decimal_places=1,
                widget=forms.NumberInput(
                    attrs={
                        "class": CONTROL_CLASS,
                        "min": "0",
                        "max": "10",
                        "step": "0.1",
                        "inputmode": "decimal",
                        "placeholder": "0–10",
                    }
                ),
            )

    def clean_school_id(self):
        school_id = self.cleaned_data["school_id"].strip()
        self.school = self.school_queryset.filter(school_id=school_id).first()
        if self.school is None:
            raise forms.ValidationError(
                "Select a school from the directory using its exact School ID."
            )
        return school_id

    @property
    def score_fields(self):
        return [self[f"score_{code}"] for code, _label in SsaIntervention.choices]

    def to_service_payload(self, *, collector_type: str) -> dict:
        return {
            "schoolId": self.cleaned_data["school_id"],
            "dateOfSsa": self.cleaned_data["date_of_ssa"].isoformat(),
            "collectorType": collector_type,
            "scores": [
                {
                    "intervention": code,
                    "score": float(self.cleaned_data[f"score_{code}"]),
                }
                for code, _label in SsaIntervention.choices
            ],
        }
