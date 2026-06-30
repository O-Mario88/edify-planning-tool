# Generated for the central Cost Catalogue. Creates the CostCatalogue model and
# (data step) seeds one active catalogue for the operational FY, attaching every
# existing CostSetting row to it — so the first boot already has an "active CD
# catalogue" and snapshotting can stamp catalogue id + version from day one.
import apps.core.cuid
import apps.core.models
import django.db.models.deletion
from django.db import migrations, models


def _seed_active_catalogue(apps, schema_editor):
    """Create one active CostCatalogue for the operational FY and attach all
    existing CostSetting rows to it. Idempotent — skips if a catalogue exists."""
    CostCatalogue = apps.get_model("budget", "CostCatalogue")
    CostSetting = apps.get_model("budget", "CostSetting")
    if CostCatalogue.objects.exists():
        return
    from django.conf import settings
    fy = getattr(settings, "OPERATIONAL_FY", None)
    if not fy:
        try:
            from apps.core.fy import get_operational_fy
            fy = get_operational_fy()
        except Exception:  # noqa: BLE001
            fy = "2026"
    country = getattr(settings, "COUNTRY", "Uganda")
    catalogue = CostCatalogue.objects.create(
        country=country, fy=str(fy), version=1, is_active=True,
        label=f"{country} FY{fy} Country Cost Catalogue",
    )
    CostSetting.objects.filter(catalogue__isnull=True).update(catalogue=catalogue)


class Migration(migrations.Migration):

    dependencies = [
        ('budget', '0002_alter_costsetting_unit_cost_and_more'),
    ]

    operations = [
        migrations.CreateModel(
            name='CostCatalogue',
            fields=[
                ('created_at', models.DateTimeField(auto_now_add=True, db_index=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('id', apps.core.models.CuidField(default=apps.core.cuid.cuid, max_length=30, primary_key=True, serialize=False)),
                ('country', models.CharField(default='Uganda', max_length=64)),
                ('fy', models.CharField(max_length=16)),
                ('version', models.IntegerField(default=1)),
                ('is_active', models.BooleanField(default=True)),
                ('label', models.CharField(blank=True, max_length=255, null=True)),
                ('published_by', models.CharField(blank=True, max_length=30, null=True)),
                ('activated_at', models.DateTimeField(blank=True, null=True)),
            ],
            options={
                'db_table': 'cost_catalogue',
                'ordering': ['-fy', '-version'],
                'constraints': [models.UniqueConstraint(condition=models.Q(('is_active', True)), fields=('country', 'fy', 'is_active'), name='uniq_active_catalogue_per_country_fy'), models.UniqueConstraint(fields=('country', 'fy', 'version'), name='uniq_catalogue_country_fy_version')],
            },
        ),
        migrations.AddField(
            model_name='costsetting',
            name='catalogue',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='rates', to='budget.costcatalogue'),
        ),
        migrations.RunPython(_seed_active_catalogue, migrations.RunPython.noop),
    ]

