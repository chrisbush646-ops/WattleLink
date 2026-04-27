import logging

from config.celery import app

logger = logging.getLogger(__name__)


@app.task(bind=True, max_retries=1, default_retry_delay=10)
def build_export_package_task(self, package_id: int):
    """Build the annotated PDF and metadata snapshot for an ExportPackage."""
    from django.core.files.base import ContentFile
    from django.utils import timezone

    from apps.accounts.managers import set_current_tenant
    from apps.claims.models import CoreClaim
    from apps.export.models import ExportPackage
    from apps.export.services.annotate import annotate_pdf, build_metadata_snapshot

    package = None
    try:
        package = ExportPackage.all_objects.select_related("paper", "tenant").get(pk=package_id)
        set_current_tenant(package.tenant)

        package.status = ExportPackage.Status.PROCESSING
        package.save(update_fields=["status"])

        paper = package.paper
        claims = list(
            CoreClaim.all_objects.filter(
                paper=paper, status=CoreClaim.Status.APPROVED, deleted_at__isnull=True
            ).select_related("reviewed_by")
        )

        # Read source PDF bytes
        pdf_bytes = b""
        if paper.source_file:
            paper.source_file.seek(0)
            pdf_bytes = paper.source_file.read()

        annotated_bytes = annotate_pdf(pdf_bytes, claims)
        metadata = build_metadata_snapshot(paper, claims)

        filename = f"export_{paper.pk}_{package_id}.pdf"
        package.annotated_pdf.save(filename, ContentFile(annotated_bytes), save=False)
        package.metadata_json = metadata
        package.claim_count = len(claims)
        package.status = ExportPackage.Status.READY
        package.completed_at = timezone.now()
        package.save()

        logger.info("Export package %d ready: %d claims", package_id, len(claims))

    except Exception as exc:
        logger.error("Export package %d failed: %s", package_id, exc)
        if package:
            package.status = ExportPackage.Status.FAILED
            package.error_message = str(exc)
            package.save(update_fields=["status", "error_message"])
        raise self.retry(exc=exc)

    finally:
        set_current_tenant(None)
