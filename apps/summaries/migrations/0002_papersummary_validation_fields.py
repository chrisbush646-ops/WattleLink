from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("summaries", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="papersummary",
            name="validation_warnings",
            field=models.JSONField(blank=True, default=list),
        ),
        migrations.AddField(
            model_name="papersummary",
            name="confidence_flags",
            field=models.JSONField(blank=True, default=list),
        ),
    ]
