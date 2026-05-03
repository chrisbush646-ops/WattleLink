from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("kol", "0005_koltalking_point"),
    ]

    operations = [
        migrations.AddField(
            model_name="kol",
            name="kol_type",
            field=models.CharField(
                choices=[
                    ("PHYSICIAN", "Physician KOL"),
                    ("RESEARCH", "Research KOL"),
                    ("BOTH", "Research & Physician"),
                ],
                default="PHYSICIAN",
                help_text="Physician KOL, Research KOL, or both",
                max_length=20,
            ),
        ),
    ]
