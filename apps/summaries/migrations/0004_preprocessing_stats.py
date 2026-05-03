from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("summaries", "0003_methodology_jsonfield"),
    ]

    operations = [
        migrations.AddField(
            model_name="papersummary",
            name="preprocessing_stats",
            field=models.JSONField(blank=True, default=dict),
        ),
    ]
