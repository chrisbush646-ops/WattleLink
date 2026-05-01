from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("claims", "0003_mlr_fields"),
    ]

    operations = [
        migrations.AddField(
            model_name="coreclaim",
            name="commercial_headline",
            field=models.TextField(
                blank=True,
                help_text="Plain-language headline for marketing/sales use. Data-anchored, no extrapolation.",
            ),
        ),
    ]
