import logging
from config.celery import app

logger = logging.getLogger(__name__)


@app.task(bind=True, max_retries=2, default_retry_delay=30)
def discover_kols_task(self, paper_id: int, tenant_id: int):
    """
    Run AI discovery on a paper, creating KOLCandidate records for review.
    Chains a verification task for each candidate.
    """
    from apps.accounts.models import Tenant
    from apps.accounts.managers import set_current_tenant
    from apps.literature.models import Paper
    from apps.kol.models import KOLCandidate
    from apps.kol.services.discovery import discover_kols

    try:
        tenant = Tenant.objects.get(pk=tenant_id)
        set_current_tenant(tenant)
        paper = Paper.all_objects.get(pk=paper_id, tenant=tenant)
        candidates_data = discover_kols(paper)

        created_ids = []
        for c in candidates_data:
            name = c.get("name", "").strip()
            if not name:
                continue

            # Avoid exact-name duplicates for the same paper
            candidate, created = KOLCandidate.objects.get_or_create(
                tenant=tenant,
                paper=paper,
                name=name,
                defaults={
                    "institution": c.get("institution", ""),
                    "specialty": c.get("specialty", ""),
                    "tier": int(c.get("tier", 3)),
                    "location": c.get("location", ""),
                    "bio": c.get("bio", ""),
                    "relevance_note": c.get("relevance_note", ""),
                    "is_author": c.get("is_author", False),
                    "status": KOLCandidate.Status.PENDING,
                },
            )
            if created:
                created_ids.append(candidate.pk)

        # Chain verification for each new candidate
        for candidate_pk in created_ids:
            verify_kol_candidate_task.delay(candidate_pk)

        if created_ids:
            from apps.audit.helpers import log_task_action
            from apps.audit.models import AuditLog
            log_task_action(tenant, paper, AuditLog.Action.AI_DRAFT,
                            after={"candidates_created": len(created_ids)})

        logger.info(
            "KOL discovery complete for paper %s: %d new candidates",
            paper_id, len(created_ids),
        )

    except Exception as exc:
        logger.error("KOL discovery failed for paper %s: %s", paper_id, exc)
        raise self.retry(exc=exc)

    finally:
        set_current_tenant(None)


@app.task(bind=True, max_retries=2, default_retry_delay=60)
def verify_kol_candidate_task(self, candidate_pk: int):
    """
    Run currency verification on a single KOLCandidate.
    Updates verification_status and verification_note.
    """
    from django.utils import timezone
    from apps.kol.models import KOLCandidate
    from apps.kol.services.verify import verify_kol_currency

    try:
        candidate = KOLCandidate.all_objects.select_related("tenant").get(pk=candidate_pk)
        result = verify_kol_currency(candidate)

        candidate.verification_status = result["current_status"]
        candidate.verification_note = result["note"]
        candidate.verification_concerns = result["concerns"]
        candidate.verified_at = timezone.now()
        candidate.save(update_fields=[
            "verification_status", "verification_note",
            "verification_concerns", "verified_at",
        ])

        from apps.audit.helpers import log_task_action
        from apps.audit.models import AuditLog
        log_task_action(candidate.tenant, candidate, AuditLog.Action.AI_DRAFT,
                        after={"verification_status": result["current_status"]})

        logger.info(
            "KOL verification complete for candidate %s: %s",
            candidate_pk, result["current_status"],
        )

    except Exception as exc:
        logger.error("KOL verification failed for candidate %s: %s", candidate_pk, exc)
        raise self.retry(exc=exc)
