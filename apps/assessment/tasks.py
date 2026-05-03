import logging

from config.celery import app

logger = logging.getLogger(__name__)


@app.task(bind=True, max_retries=2, default_retry_delay=30)
def run_ai_assessment_task(self, paper_id: int, tenant_id: int):
    """
    Async AI pre-fill for GRADE + RoB 2.
    Creates or updates GradeAssessment and RobAssessment with AI_DRAFT status.
    """
    from apps.accounts.models import Tenant
    from apps.accounts.managers import set_current_tenant
    from apps.ai.services import set_task_progress
    from apps.literature.models import Paper
    from apps.assessment.models import GradeAssessment, RobAssessment
    from apps.assessment.services.ai_assessment import (
        run_ai_assessment,
        apply_grade_result,
        apply_rob_result,
    )

    task_id = self.request.id

    try:
        tenant = Tenant.objects.get(pk=tenant_id)
        set_current_tenant(tenant)
        paper = Paper.all_objects.get(pk=paper_id, tenant=tenant)

        set_task_progress(task_id, "calling_api", "Calling Claude API…")
        result = run_ai_assessment(paper)

        set_task_progress(task_id, "saving", "Saving results…")

        grade_data = result.get("grade", {})
        rob_data = result.get("rob", {})

        grade, _ = GradeAssessment.all_objects.get_or_create(
            paper=paper,
            defaults={"tenant": tenant},
        )
        apply_grade_result(grade, grade_data)
        grade.save()

        rob, _ = RobAssessment.all_objects.get_or_create(
            paper=paper,
            defaults={"tenant": tenant},
        )
        apply_rob_result(rob, rob_data)
        rob.save()

        from apps.audit.helpers import log_task_action
        from apps.audit.models import AuditLog
        log_task_action(tenant, paper, AuditLog.Action.AI_DRAFT,
                        after={"assessment": "AI pre-fill complete"})

        set_task_progress(task_id, "complete", "Done")
        logger.info("AI assessment complete for paper %s", paper_id)

    except Exception as exc:
        set_task_progress(task_id, "failed", f"Failed: {exc}")
        logger.error("AI assessment failed for paper %s: %s", paper_id, exc)
        raise self.retry(exc=exc)

    finally:
        set_current_tenant(None)
