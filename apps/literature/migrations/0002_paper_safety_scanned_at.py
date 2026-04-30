from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("literature", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="paper",
            name="safety_scanned_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
