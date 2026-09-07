# The partner roster (owner, 2026-09-07): the staff and volunteers who deliver
# for a partner organisation, as a table on its profile. Not a login and not a
# StaffProfile — see PartnerMember's docstring.

import apps.core.cuid
import apps.core.models
import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("partners", "0018_partnerassignment_uniq_live_partner_support_slot"),
    ]

    operations = [
        migrations.CreateModel(
            name="PartnerMember",
            fields=[
                ("created_at", models.DateTimeField(auto_now_add=True, db_index=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "id",
                    apps.core.models.CuidField(
                        default=apps.core.cuid.cuid,
                        max_length=30,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                ("name", models.CharField(max_length=255)),
                (
                    "role",
                    models.CharField(
                        choices=[("staff", "Staff"), ("volunteer", "Volunteer")],
                        default="staff",
                        max_length=16,
                    ),
                ),
                ("title", models.CharField(blank=True, default="", max_length=128)),
                ("phone", models.CharField(blank=True, default="", max_length=64)),
                ("email", models.EmailField(blank=True, default="", max_length=254)),
                ("active", models.BooleanField(default=True)),
                (
                    "added_by_user_id",
                    models.CharField(blank=True, max_length=30, null=True),
                ),
                (
                    "partner",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="members",
                        to="partners.partner",
                    ),
                ),
            ],
            options={
                "db_table": "partner_member",
                "ordering": ["role", "name"],
                "indexes": [
                    models.Index(
                        fields=["partner", "active"],
                        name="partner_mem_partner_f81003_idx",
                    )
                ],
            },
        ),
    ]
