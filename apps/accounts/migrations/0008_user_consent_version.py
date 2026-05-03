from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0007_extend_password_field"),
    ]

    operations = [
        migrations.AddField(
            model_name="user",
            name="consent_version",
            field=models.PositiveIntegerField(default=0),
        ),
    ]
