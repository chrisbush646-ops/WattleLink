import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0005_user_tab_permissions"),
    ]

    operations = [
        # New fields on Tenant
        migrations.AddField(
            model_name="tenant",
            name="billing_email",
            field=models.EmailField(blank=True),
        ),
        migrations.AddField(
            model_name="tenant",
            name="plan",
            field=models.CharField(
                choices=[
                    ("TRIAL", "Trial"),
                    ("STARTER", "Starter"),
                    ("PROFESSIONAL", "Professional"),
                    ("ENTERPRISE", "Enterprise"),
                ],
                default="TRIAL",
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name="tenant",
            name="is_active",
            field=models.BooleanField(default=True),
        ),
        migrations.AddField(
            model_name="tenant",
            name="trial_ends_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="tenant",
            name="max_users",
            field=models.PositiveIntegerField(default=10),
        ),
        # New Invitation model
        migrations.CreateModel(
            name="Invitation",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("email", models.EmailField()),
                (
                    "role",
                    models.CharField(
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
                ("token", models.CharField(max_length=64, unique=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("expires_at", models.DateTimeField()),
                ("accepted_at", models.DateTimeField(blank=True, null=True)),
                (
                    "invited_by",
                    models.ForeignKey(
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="sent_invitations",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "tenant",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="invitations",
                        to="accounts.tenant",
                    ),
                ),
            ],
        ),
    ]
