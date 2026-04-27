import logging

from config.celery import app

logger = logging.getLogger(__name__)


@app.task(bind=True, max_retries=2, default_retry_delay=30)
def run_ai_summary_task(self, paper_id: int, tenant_id: int):
    """Async AI summarisation — creates/updates PaperSummary and FindingsRows."""
    from apps.accounts.models import Tenant
    from apps.accounts.managers import set_current_tenant
    from apps.literature.models import Paper
    from apps.summaries.models import PaperSummary, FindingsRow
    from apps.summaries.services.ai_summary import run_ai_summary, apply_summary_result

    try:
        tenant = Tenant.objects.get(pk=tenant_id)
        set_current_tenant(tenant)
        paper = Paper.all_objects.get(pk=paper_id, tenant=tenant)

        result = run_ai_summary(paper)

        summary, created = PaperSummary.all_objects.get_or_create(
            paper=paper,
            defaults={"tenant": tenant},
        )

        findings_data = result.get("findings", [])
        row_kwargs = apply_summary_result(summary, findings_data, result)
        summary.save()

        # Replace all existing findings rows
        FindingsRow.objects.filter(summary=summary).delete()
        FindingsRow.objects.bulk_create([
            FindingsRow(summary=summary, **kw) for kw in row_kwargs
        ])

        logger.info("AI summary complete for paper %s", paper_id)

    except Exception as exc:
        logger.error("AI summary failed for paper %s: %s", paper_id, exc)
        raise self.retry(exc=exc)

    finally:
        set_current_tenant(None)
