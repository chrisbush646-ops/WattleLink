from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("literature", "0002_paper_safety_scanned_at"),
    ]

    operations = [
        migrations.AddField(
            model_name="savedsearch",
            name="last_result_pmids",
            field=models.JSONField(default=list),
        ),
    ]
