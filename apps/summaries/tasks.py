import logging

from config.celery import app

logger = logging.getLogger(__name__)


def _ensure_full_text(paper) -> None:
    """
    Make sure paper.full_text contains the richest available text before summarising.
    Priority: PDF source file → PMC full text → keep existing (abstract).
    Updates paper.full_text and saves to DB if a longer version is found.
    """
    from apps.literature.services.pdf import extract_text

    if paper.source_file:
        try:
            text = extract_text(paper.source_file.path)
            if len(text) > len(paper.full_text or ""):
                paper.full_text = text[:500_000]
                paper.save(update_fields=["full_text"])
                logger.info("Used PDF text for paper %s (%d chars)", paper.pk, len(text))
                return
        except Exception as exc:
            logger.warning("PDF extraction failed for paper %s: %s", paper.pk, exc)

    if len(paper.full_text or "") < 4_000 and paper.pmcid:
        try:
            from apps.literature.services.pubmed import fetch_pmc_full_text
            fetch_pmc_full_text(paper)
            paper.refresh_from_db(fields=["full_text"])
        except Exception as exc:
            logger.warning("PMC fetch failed for paper %s: %s", paper.pk, exc)


@app.task(bind=True, max_retries=2, default_retry_delay=30)
def run_ai_summary_task(self, paper_id: int, tenant_id: int):
    """Async AI summarisation — creates/updates PaperSummary and FindingsRows."""
    from apps.accounts.models import Tenant
    from apps.accounts.managers import set_current_tenant
    from apps.literature.models import Paper
    from apps.summaries.models import PaperSummary, FindingsRow
    from apps.summaries.services.ai_summary import run_ai_summary, apply_summary_result
    from apps.summaries.services.validation import validate_summary

    try:
        tenant = Tenant.objects.get(pk=tenant_id)
        set_current_tenant(tenant)
        paper = Paper.all_objects.get(pk=paper_id, tenant=tenant)

        _ensure_full_text(paper)
        result = run_ai_summary(paper)

        summary, created = PaperSummary.all_objects.get_or_create(
            paper=paper,
            defaults={"tenant": tenant},
        )

        findings_data = result.get("findings", [])
        row_kwargs = apply_summary_result(summary, findings_data, result)

        warnings = validate_summary(result, paper.full_text or "")
        summary.validation_warnings = warnings

        summary.save()

        # Replace all existing findings rows
        FindingsRow.objects.filter(summary=summary).delete()
        FindingsRow.objects.bulk_create([
            FindingsRow(summary=summary, **kw) for kw in row_kwargs
        ])

        from apps.audit.helpers import log_task_action
        from apps.audit.models import AuditLog
        log_task_action(tenant, paper, AuditLog.Action.AI_DRAFT,
                        after={"summary": "AI summary generated", "findings_rows": len(findings_data)})

        logger.info("AI summary complete for paper %s", paper_id)

    except Exception as exc:
        logger.error("AI summary failed for paper %s: %s", paper_id, exc)
        raise self.retry(exc=exc)

    finally:
        set_current_tenant(None)
