from django.db import migrations, models


def convert_methodology_to_json(apps, schema_editor):
    PaperSummary = apps.get_model("summaries", "PaperSummary")
    blank_structure = {
        "study_design": "",
        "population": {"description": "", "sample_size": "", "demographics": ""},
        "intervention": "",
        "comparator": "",
        "follow_up": "",
        "primary_endpoint": "",
        "secondary_endpoints": [],
        "statistical_methods": "",
        "setting": "",
        "source_reference": "",
    }
    for summary in PaperSummary.objects.all():
        old_text = (summary.methodology_old or "").strip()
        if old_text:
            structure = dict(blank_structure)
            structure["study_design"] = old_text
            structure["population"] = {"description": "", "sample_size": "", "demographics": ""}
        else:
            structure = dict(blank_structure)
            structure["population"] = {"description": "", "sample_size": "", "demographics": ""}
        summary.methodology_structured = structure
        summary.save(update_fields=["methodology_structured"])


class Migration(migrations.Migration):

    dependencies = [
        ("summaries", "0002_papersummary_validation_fields"),
    ]

    operations = [
        migrations.AddField(
            model_name="papersummary",
            name="methodology_structured",
            field=models.JSONField(blank=True, default=dict),
        ),
        migrations.RenameField(
            model_name="papersummary",
            old_name="methodology",
            new_name="methodology_old",
        ),
        migrations.RunPython(convert_methodology_to_json, migrations.RunPython.noop),
        migrations.RemoveField(
            model_name="papersummary",
            name="methodology_old",
        ),
        migrations.RenameField(
            model_name="papersummary",
            old_name="methodology_structured",
            new_name="methodology",
        ),
        migrations.AlterField(
            model_name="findingsrow",
            name="category",
            field=models.CharField(
                choices=[
                    ("Primary", "Primary"),
                    ("Secondary", "Secondary"),
                    ("Post-hoc", "Post-hoc"),
                    ("Safety", "Safety"),
                    ("Other", "Other"),
                ],
                default="Primary",
                max_length=20,
            ),
        ),
    ]
