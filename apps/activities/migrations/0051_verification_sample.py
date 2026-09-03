import django.db.models.deletion
from django.db import migrations, models

import apps.core.cuid
import apps.core.models


class Migration(migrations.Migration):
    dependencies = [
        ("activities", "0050_visit_request_owner_approval"),
    ]

    operations = [
        migrations.CreateModel(
            name="VerificationSample",
            fields=[
                ("created_at", models.DateTimeField(auto_now_add=True, db_index=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("id", apps.core.models.CuidField(default=apps.core.cuid.cuid, max_length=30, primary_key=True, serialize=False)),
                ("original_verifier", models.CharField(max_length=30)),
                ("sampled_at", models.DateTimeField(auto_now_add=True)),
                ("sampled_by", models.CharField(default="system", max_length=30)),
                ("status", models.CharField(choices=[("pending", "Pending"), ("confirmed", "Confirmed"), ("disputed", "Disputed")], default="pending", max_length=16)),
                ("outcome_note", models.TextField(blank=True, default="")),
                ("checked_by", models.CharField(blank=True, max_length=30, null=True)),
                ("checked_at", models.DateTimeField(blank=True, null=True)),
                ("activity", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="verification_samples", to="activities.activity")),
            ],
            options={
                "db_table": "ia_verification_sample",
                "indexes": [models.Index(fields=["status", "sampled_at"], name="ia_verifica_status_a7005e_idx")],
            },
        ),
    ]
