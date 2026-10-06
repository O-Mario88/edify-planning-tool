"""A training every school may attend, on top of its entitlement.

Owner, 2026-10-06: "School Improvement Planning training is universal every
schools can attend. for the rest of the trainings, Core gets 4 training and
clients get 1 training ontop of School improvement training."

Later the same day: "School improvement Planning is actually SSA training",
so the training that carries it is the catalogue's SSA Training.

The column only. Which trainings carry it is the governed seed's
(``seed_data.UNIVERSAL_TRAINING_CODES``), installed after every migrate, so
this migration writes no rows.
"""

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("activity_catalogue", "0015_item_edited_fields"),
    ]

    operations = [
        migrations.AddField(
            model_name="activitycatalogueitem",
            name="universal_training",
            field=models.BooleanField(default=False),
        ),
    ]
