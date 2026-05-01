from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0004_add_editor_viewer_roles"),
    ]

    operations = [
        migrations.AddField(
            model_name="user",
            name="tab_permissions",
            field=models.JSONField(
                default=dict,
                help_text="Per-module overrides: {module_key: 'editor'|'viewer'|'none'}",
            ),
        ),
    ]
