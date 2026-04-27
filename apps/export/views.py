import logging

from django.contrib.auth.decorators import login_required
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, render
from django.views.decorators.http import require_POST

from apps.audit.helpers import log_action
from apps.audit.models import AuditLog
from apps.claims.models import CoreClaim
from apps.literature.models import Paper

from .models import ExportPackage

logger = logging.getLogger(__name__)


@login_required
def export_panel(request, paper_pk):
    """HTMX — export panel for a paper (lazy-loaded in paper detail modal)."""
    paper = get_object_or_404(Paper, pk=paper_pk, tenant=request.tenant)
    approved_claims = CoreClaim.all_objects.filter(
        paper=paper, status=CoreClaim.Status.APPROVED, deleted_at__isnull=True
    )
    packages = ExportPackage.objects.filter(paper=paper).order_by("-created_at")[:5]
    return render(request, "export/partials/export_panel.html", {
        "paper": paper,
        "approved_claims": approved_claims,
        "approved_count": approved_claims.count(),
        "packages": packages,
    })


@login_required
@require_POST
def create_export(request, paper_pk):
    """Trigger async export package build."""
    paper = get_object_or_404(Paper, pk=paper_pk, tenant=request.tenant)

    approved_claims = CoreClaim.all_objects.filter(
        paper=paper, status=CoreClaim.Status.APPROVED, deleted_at__isnull=True
    )
    if not approved_claims.exists():
        return render(request, "export/partials/export_panel.html", {
            "paper": paper,
            "approved_claims": approved_claims,
            "approved_count": 0,
            "packages": ExportPackage.objects.filter(paper=paper).order_by("-created_at")[:5],
            "error": "No approved claims to export. Approve at least one claim first.",
        })

    package = ExportPackage.objects.create(
        tenant=request.tenant,
        paper=paper,
        created_by=request.user,
        status=ExportPackage.Status.PENDING,
    )
    log_action(request, package, AuditLog.Action.CREATE,
               after={"paper": paper.pk, "status": package.status})

    from .tasks import build_export_package_task
    build_export_package_task.delay(package.pk)

    return render(request, "export/partials/export_processing.html", {
        "paper": paper,
        "package": package,
    })


@login_required
def download_export(request, package_pk):
    """Serve the annotated PDF for download."""
    package = get_object_or_404(
        ExportPackage, pk=package_pk,
        tenant=request.tenant,
        status=ExportPackage.Status.READY,
    )
    if not package.annotated_pdf:
        raise Http404

    log_action(request, package, AuditLog.Action.EXPORT,
               after={"package": package.pk})

    response = FileResponse(
        package.annotated_pdf.open("rb"),
        content_type="application/pdf",
        as_attachment=True,
        filename=f"{package.paper.doi or package.paper.pk}_annotated.pdf",
    )
    return response


@login_required
def poll_export(request, package_pk):
    """HTMX poll — returns current state of an export package."""
    package = get_object_or_404(ExportPackage, pk=package_pk, tenant=request.tenant)
    paper = package.paper
    if package.status == ExportPackage.Status.READY:
        packages = ExportPackage.objects.filter(paper=paper).order_by("-created_at")[:5]
        approved_claims = CoreClaim.all_objects.filter(
            paper=paper, status=CoreClaim.Status.APPROVED, deleted_at__isnull=True
        )
        return render(request, "export/partials/export_panel.html", {
            "paper": paper,
            "approved_claims": approved_claims,
            "approved_count": approved_claims.count(),
            "packages": packages,
        })
    return render(request, "export/partials/export_processing.html", {
        "paper": paper,
        "package": package,
    })
