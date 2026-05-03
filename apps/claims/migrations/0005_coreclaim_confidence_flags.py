from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("claims", "0004_coreclaim_commercial_headline"),
    ]

    operations = [
        migrations.AddField(
            model_name="coreclaim",
            name="confidence_flags",
            field=models.JSONField(blank=True, default=list),
        ),
    ]
