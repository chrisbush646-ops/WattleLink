from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('claims', '0002_compliance_fields'),
    ]

    operations = [
        migrations.AddField(
            model_name='coreclaim',
            name='mlr_compliance_score',
            field=models.PositiveSmallIntegerField(blank=True, null=True, help_text='0-100 MA Code compliance score from AI MLR auditor.'),
        ),
        migrations.AddField(
            model_name='coreclaim',
            name='mlr_verdict',
            field=models.CharField(blank=True, max_length=10, help_text='PASS (80-100), WARN (50-79), or FAIL (0-49).'),
        ),
        migrations.AddField(
            model_name='coreclaim',
            name='mlr_red_flags',
            field=models.JSONField(default=list),
        ),
        migrations.AddField(
            model_name='coreclaim',
            name='mlr_rule_results',
            field=models.JSONField(default=dict, help_text='Per-rule breakdown: {rule: {pass, deduction, finding}}'),
        ),
        migrations.AddField(
            model_name='coreclaim',
            name='mlr_rationale',
            field=models.TextField(blank=True),
        ),
        migrations.AddField(
            model_name='coreclaim',
            name='mlr_checked_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
