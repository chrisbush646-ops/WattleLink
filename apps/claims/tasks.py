import logging

from config.celery import app

logger = logging.getLogger(__name__)


@app.task(bind=True, max_retries=2, default_retry_delay=30)
def extract_claims_task(self, paper_id: int, tenant_id: int):
    """Async claim extraction — creates AI_DRAFT CoreClaim rows for the paper."""
    from apps.accounts.models import Tenant
    from apps.accounts.managers import set_current_tenant
    from apps.literature.models import Paper
    from apps.claims.models import CoreClaim
    from apps.claims.services.extraction import extract_claims

    try:
        tenant = Tenant.objects.get(pk=tenant_id)
        set_current_tenant(tenant)
        paper = Paper.all_objects.get(pk=paper_id, tenant=tenant)

        claims_data = extract_claims(paper)

        # Delete existing AI drafts only — preserve any human-reviewed claims
        CoreClaim.all_objects.filter(paper=paper, status=CoreClaim.Status.AI_DRAFT).delete()

        CoreClaim.all_objects.bulk_create([
            CoreClaim(
                tenant=tenant,
                paper=paper,
                claim_text=c.get("claim_text", ""),
                endpoint_type=c.get("endpoint_type", CoreClaim.EndpointType.OTHER),
                source_passage=c.get("source_passage", ""),
                source_reference=c.get("source_reference", ""),
                fair_balance=c.get("fair_balance", ""),
                fair_balance_reference=c.get("fair_balance_reference", ""),
                fidelity_checklist=c.get("fidelity_checklist", {}),
                status=CoreClaim.Status.AI_DRAFT,
                ai_generated=True,
            )
            for c in claims_data
        ])

        logger.info("Claim extraction complete for paper %s (%d claims)", paper_id, len(claims_data))

    except Exception as exc:
        logger.error("Claim extraction failed for paper %s: %s", paper_id, exc)
        raise self.retry(exc=exc)

    finally:
        set_current_tenant(None)
