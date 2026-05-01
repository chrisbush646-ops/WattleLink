import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("kol", "0004_alter_kolcandidate_search_query"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="KOLTalkingPoint",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("text", models.TextField()),
                ("source_note", models.CharField(blank=True, max_length=300)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("kol", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="talking_points", to="kol.kol")),
                ("created_by", models.ForeignKey(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name="kol_talking_points",
                    to=settings.AUTH_USER_MODEL,
                )),
            ],
            options={"ordering": ["created_at"]},
        ),
    ]
