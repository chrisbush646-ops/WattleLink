from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("literature", "0003_savedsearch_last_result_pmids"),
    ]

    operations = [
        migrations.AddField(
            model_name="savedsearch",
            name="refinement_terms",
            field=models.JSONField(default=list),
        ),
        migrations.AddField(
            model_name="savedsearch",
            name="exclusion_terms",
            field=models.JSONField(default=list),
        ),
        migrations.AddField(
            model_name="savedsearch",
            name="result_count_history",
            field=models.JSONField(default=list),
        ),
        migrations.AddField(
            model_name="savedsearch",
            name="ai_suggestions_used",
            field=models.JSONField(default=list),
        ),
    ]
