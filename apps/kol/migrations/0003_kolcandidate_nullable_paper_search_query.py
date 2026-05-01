from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("kol", "0002_add_kol_candidate"),
        ("literature", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="kolcandidate",
            name="search_query",
            field=models.CharField(
                blank=True,
                max_length=400,
                help_text="Keyword query used to discover this candidate (set for keyword-search candidates, blank for paper-extracted ones).",
            ),
        ),
        migrations.AlterField(
            model_name="kolcandidate",
            name="paper",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="kol_candidates",
                to="literature.paper",
            ),
        ),
    ]
