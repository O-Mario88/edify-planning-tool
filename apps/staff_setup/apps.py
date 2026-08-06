"""Staff-setup app — admin resolution of uploaded staff-name candidates.

When a school upload carries a Staff Name that doesn't match an existing user,
the upload creates a StaffSetupCandidate. This app is the Admin surface to turn
those candidates into real users (or merge them with existing ones) and link the
affected schools to the resolved user — completing the ownership bridge.
"""

from django.apps import AppConfig


class StaffSetupConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.staff_setup"
    label = "staff_setup"
