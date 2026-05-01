from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0003_compliance_fields"),
    ]

    operations = [
        migrations.AlterField(
            model_name="user",
            name="role",
            field=models.CharField(
                choices=[
                    ("MEDICAL_LEAD", "Medical Lead"),
                    ("MEDICAL_AFFAIRS", "Medical Affairs"),
                    ("COMMERCIAL", "Commercial"),
                    ("ADMIN", "Admin"),
                    ("EDITOR", "Editor"),
                    ("VIEWER", "Viewer"),
                ],
                default="MEDICAL_AFFAIRS",
                max_length=20,
            ),
        ),
    ]
