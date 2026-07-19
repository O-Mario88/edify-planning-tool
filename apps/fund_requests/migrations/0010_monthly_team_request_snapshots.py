from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("fund_requests", "0009_partnerpayment_uniq_partner_payment_per_activity"),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name="fundrequestitem",
            name="uniq_costline_period",
        ),
        migrations.RemoveConstraint(
            model_name="fundrequest",
            name="uniq_request_period_owner",
        ),
        migrations.AddConstraint(
            model_name="fundrequest",
            constraint=models.UniqueConstraint(
                fields=("submitted_by_user_id", "period", "period_key", "scope"),
                name="uniq_request_period_owner",
            ),
        ),
    ]
