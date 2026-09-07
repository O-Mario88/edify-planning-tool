"""Forms for the public school loan-application surface."""

import re

from django import forms

from apps.schools.models import School

from .models import (
    LoanApplication,
    LoanPurpose,
    MfiOrganization,
    OPEN_LOAN_APPLICATION_STATUSES,
)


class PublicLoanApplicationForm(forms.ModelForm):
    school_id = forms.CharField(label="Edify school ID", max_length=64)
    school_name = forms.CharField(label="School name", max_length=512)
    consent = forms.BooleanField(
        label="I confirm the school has authorized this application and may be contacted about it."
    )
    website = forms.CharField(required=False, widget=forms.HiddenInput)

    class Meta:
        model = LoanApplication
        fields = (
            "applicant_name",
            "applicant_role",
            "applicant_phone",
            "applicant_email",
            "purpose",
            "preferred_mfi",
            "requested_amount",
            "intended_use",
            "requested_term_months",
            "repayment_frequency",
        )
        labels = {
            "applicant_name": "Your full name",
            "applicant_role": "Role at the school",
            "applicant_phone": "Phone number",
            "applicant_email": "Email address (optional)",
            "purpose": "Loan purpose",
            "preferred_mfi": "Preferred lending partner (optional)",
            "requested_amount": "Amount requested (UGX)",
            "intended_use": "How will the school use the loan?",
            "requested_term_months": "Preferred loan term (months)",
            "repayment_frequency": "Preferred repayment frequency",
        }
        widgets = {
            "applicant_phone": forms.TextInput(attrs={"inputmode": "tel"}),
            "requested_amount": forms.NumberInput(
                attrs={"min": "1", "step": "1000", "inputmode": "decimal"}
            ),
            "requested_term_months": forms.NumberInput(attrs={"min": "1", "max": "120"}),
            "intended_use": forms.Textarea(attrs={"rows": 4}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["purpose"].queryset = LoanPurpose.objects.filter(active=True).order_by(
            "label"
        )
        self.fields["preferred_mfi"].queryset = MfiOrganization.objects.filter(
            active=True, deleted_at__isnull=True
        ).order_by("name")
        self.fields["preferred_mfi"].empty_label = "No preference"
        for field in self.fields.values():
            field.widget.attrs.setdefault("class", "w-full")

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("website"):
            raise forms.ValidationError("Unable to submit this application.")
        school_id = (cleaned.get("school_id") or "").strip()
        school_name = (cleaned.get("school_name") or "").strip()
        school = School.objects.filter(
            school_id__iexact=school_id, name__iexact=school_name, deleted_at__isnull=True
        ).first()
        if not school:
            self.add_error(
                "school_name",
                "The school ID and name do not match our records. Ask your Edify contact to confirm them.",
            )
        else:
            cleaned["school"] = school
            if LoanApplication.objects.filter(
                school=school,
                status__in=OPEN_LOAN_APPLICATION_STATUSES,
                deleted_at__isnull=True,
            ).exists():
                self.add_error(
                    "school_id",
                    "This school already has an open loan application. Contact your Edify portfolio owner for an update.",
                )
        return cleaned

    def clean_applicant_phone(self):
        value = (self.cleaned_data.get("applicant_phone") or "").strip()
        normalized = re.sub(r"[\s().-]", "", value)
        if normalized.startswith("00"):
            normalized = f"+{normalized[2:]}"
        digits = normalized[1:] if normalized.startswith("+") else normalized
        if not digits.isdigit() or not 7 <= len(digits) <= 15:
            raise forms.ValidationError(
                "Enter a valid phone number, including the country code where possible."
            )
        return normalized

    def clean_requested_term_months(self):
        value = self.cleaned_data.get("requested_term_months")
        if value is not None and value > 120:
            raise forms.ValidationError("The requested loan term cannot exceed 120 months.")
        return value
