"""Per-user opt-out for the SMS money-alert channel.

The CCEO learned of approvals, returns and disbursements only through the
in-app rail, which requires being on the platform to see. Money decisions now
also go out as an SMS (apps.notifications.services) to anyone with a phone on
file; this flag lets a person switch that channel off without clearing their
number, which the MFA SMS channel still needs.
"""

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        (
            "accounts",
            "0024_temporarycoverageassignment_uniq_active_coverage_per_leave_request_and_more",
        ),
    ]

    operations = [
        migrations.AddField(
            model_name="user",
            name="sms_money_alerts",
            field=models.BooleanField(default=True),
        ),
    ]
