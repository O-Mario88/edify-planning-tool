from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("activities", "0049_activity_training_course_and_paired_visit"),
    ]

    operations = [
        migrations.AddField(
            model_name="activity",
            name="approval_owner_id",
            field=models.CharField(blank=True, default="", max_length=30),
        ),
        migrations.AddField(
            model_name="activity",
            name="owner_decided_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="activity",
            name="owner_decided_by",
            field=models.CharField(blank=True, max_length=30, null=True),
        ),
        migrations.AddField(
            model_name="activity",
            name="owner_decision_note",
            field=models.CharField(blank=True, default="", max_length=512),
        ),
        migrations.AddField(
            model_name="activity",
            name="visit_justification",
            field=models.TextField(blank=True, default=""),
        ),
        migrations.AlterField(
            model_name="activity",
            name="status",
            field=models.CharField(
                choices=[
                    ("not_planned", "Not Planned"),
                    ("awaiting_owner_approval", "Awaiting Owner Approval"),
                    ("planned", "Planned"),
                    ("scheduled", "Scheduled"),
                    ("assigned_to_partner", "Assigned to Partner"),
                    ("partner_scheduled", "Partner Scheduled"),
                    ("in_progress", "In Progress"),
                    ("completion_started", "Completion Started"),
                    ("evidence_uploaded", "Evidence Uploaded"),
                    ("evidence_accepted", "Evidence Accepted"),
                    ("salesforce_id_required", "Salesforce ID Required"),
                    ("submitted_to_pl", "Submitted to PL"),
                    ("returned_by_pl", "Returned by PL"),
                    ("awaiting_ia_verification", "Awaiting IA Verification"),
                    ("ia_verified", "IA Verified"),
                    ("accountant_confirmed", "Accountant Confirmed"),
                    ("completed", "Completed"),
                    ("returned", "Returned"),
                    ("returned_by_ia", "Returned by IA"),
                    ("closed", "Closed"),
                    ("rejected", "Rejected"),
                    ("rescheduled", "Rescheduled"),
                    ("cancelled", "Cancelled"),
                    ("deferred", "Deferred"),
                ],
                default="not_planned",
                max_length=32,
            ),
        ),
        migrations.AddIndex(
            model_name="activity",
            index=models.Index(
                fields=["approval_owner_id", "status"],
                name="activity_approva_adf30f_idx",
            ),
        ),
    ]
