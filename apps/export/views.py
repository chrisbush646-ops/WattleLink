import io
import logging

import pymupdf
from django.contrib.auth.decorators import login_required
from django.core.files.base import ContentFile
from django.db.models import Q
from django.http import FileResponse, Http404, HttpResponse
from django.shortcuts import get_object_or_404, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.audit.helpers import log_action
from apps.audit.models import AuditLog
from apps.claims.models import CoreClaim
from apps.literature.models import Paper

from .models import ExportPackage
from .services.annotate import annotate_pdf, build_metadata_snapshot

logger = logging.getLogger(__name__)

def _generate_text_pdf(paper) -> bytes:
    """Build a paginated PDF from the paper's stored full_text using PyMuPDF Story."""
    full_text = (paper.full_text or "").strip()
    if not full_text:
        return b""

    def _esc(s: str) -> str:
        return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    journal_line = _esc(paper.journal or "")
    if paper.published_date:
        journal_line += f" ({paper.published_date.year})"
    if paper.doi:
        journal_line += f" · DOI: {_esc(paper.doi)}"

    body_html = _esc(full_text).replace("\n\n", "</p><p>").replace("\n", " ")

    html = (
        f"<body style='font-family:Helvetica;font-size:10pt;line-height:1.5'>"
        f"<h1 style='font-size:13pt;margin-bottom:4pt'>{_esc(paper.title or 'Untitled')}</h1>"
        f"<p style='font-size:8pt;color:#666;margin-bottom:14pt'>{journal_line}</p>"
        f"<p>{body_html}</p>"
        f"</body>"
    )

    story = pymupdf.Story(html=html)
    buf = io.BytesIO()
    writer = pymupdf.DocumentWriter(buf)
    mediabox = pymupdf.Rect(0, 0, 595, 842)
    where = mediabox + (50, 50, -50, -50)

    more = True
    while more:
        device = writer.begin_page(mediabox)
        more, _ = story.place(where)
        story.draw(device)
        writer.end_page()

    writer.close()
    result = buf.getvalue()
    logger.info("Generated text PDF for paper %s (%d bytes)", paper.pk, len(result))
    return result


@login_required
def export_list(request):
    """Main PDF Markup & Export page."""
    q = request.GET.get("q", "").strip()
    status_filter = request.GET.get("status", "")

    papers_qs = Paper.objects.filter(tenant=request.tenant).prefetch_related(
        "export_packages", "claims"
    )
    if q:
        papers_qs = papers_qs.filter(
            Q(title__icontains=q) | Q(journal__icontains=q)
        )

    # Build rows: papers that have approved claims (export candidates)
    rows = []
    for paper in papers_qs.order_by("-updated_at"):
        approved_count = paper.claims.filter(
            status=CoreClaim.Status.APPROVED, deleted_at__isnull=True
        ).count()
        latest_pkg = paper.export_packages.order_by("-created_at").first()

        if status_filter == "ready" and (not latest_pkg or latest_pkg.status != ExportPackage.Status.READY):
            continue
        if status_filter == "awaiting" and (approved_count == 0 or latest_pkg):
            continue
        if status_filter == "failed" and (not latest_pkg or latest_pkg.status != ExportPackage.Status.FAILED):
            continue

        if approved_count > 0 or latest_pkg:
            rows.append({
                "paper": paper,
                "approved_count": approved_count,
                "latest_pkg": latest_pkg,
            })

    all_pkgs = ExportPackage.objects.filter(tenant=request.tenant)
    ready_count = all_pkgs.filter(status=ExportPackage.Status.READY).count()
    failed_count = all_pkgs.filter(status=ExportPackage.Status.FAILED).count()
    awaiting_count = Paper.objects.filter(tenant=request.tenant).filter(
        claims__status=CoreClaim.Status.APPROVED, claims__deleted_at__isnull=True
    ).distinct().count()

    ctx = {
        "rows": rows,
        "q": q,
        "status_filter": status_filter,
        "ready_count": ready_count,
        "failed_count": failed_count,
        "awaiting_count": awaiting_count,
    }
    if request.headers.get("HX-Request"):
        return render(request, "export/partials/export_list_rows.html", ctx)
    return render(request, "export/export_list.html", ctx)


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
    """Build an export package synchronously and return the updated panel."""
    paper = get_object_or_404(Paper, pk=paper_pk, tenant=request.tenant)

    approved_claims = list(CoreClaim.all_objects.filter(
        paper=paper, status=CoreClaim.Status.APPROVED, deleted_at__isnull=True
    ).select_related("reviewed_by"))

    def _panel(error=None):
        return render(request, "export/partials/export_panel.html", {
            "paper": paper,
            "approved_claims": approved_claims,
            "approved_count": len(approved_claims),
            "packages": ExportPackage.objects.filter(paper=paper).order_by("-created_at")[:5],
            "error": error,
        })

    if not approved_claims:
        return _panel("No approved claims to export. Approve at least one claim first.")

    package = ExportPackage.objects.create(
        tenant=request.tenant,
        paper=paper,
        created_by=request.user,
        status=ExportPackage.Status.PROCESSING,
    )
    log_action(request, package, AuditLog.Action.CREATE,
               after={"paper": paper.pk, "status": package.status})

    try:
        if not paper.source_file:
            if paper.full_text:
                pdf_bytes = _generate_text_pdf(paper)
            else:
                raise ValueError(
                    "No PDF or full text available for this paper. "
                    "Upload the source PDF before generating an export."
                )
        else:
            paper.source_file.seek(0)
            pdf_bytes = paper.source_file.read()

        if not pdf_bytes:
            raise ValueError("The source PDF file is empty. Re-upload the PDF and try again.")

        if not pdf_bytes[:4].startswith(b"%PDF"):
            raise ValueError(
                "The source file does not appear to be a valid PDF "
                f"(first bytes: {pdf_bytes[:8]!r}). Re-upload the PDF and try again."
            )

        annotated_bytes = annotate_pdf(pdf_bytes, approved_claims)

        if not annotated_bytes or not annotated_bytes[:4].startswith(b"%PDF"):
            raise ValueError(
                "PDF annotation produced an invalid result. "
                "This may indicate a corrupted source PDF. Re-upload the file and try again."
            )
        metadata = build_metadata_snapshot(paper, approved_claims)

        filename = f"export_{paper.pk}_{package.pk}.pdf"
        package.annotated_pdf.save(filename, ContentFile(annotated_bytes), save=False)
        package.metadata_json = metadata
        package.claim_count = len(approved_claims)
        package.status = ExportPackage.Status.READY
        package.completed_at = timezone.now()
        package.save()

        log_action(request, package, AuditLog.Action.EXPORT,
                   after={"claim_count": package.claim_count, "status": package.status})

    except Exception as exc:
        logger.error("Export failed for paper %s: %s", paper_pk, exc)
        package.status = ExportPackage.Status.FAILED
        package.error_message = str(exc)
        package.save(update_fields=["status", "error_message"])
        if request.GET.get("from") == "list":
            return render(request, "export/partials/export_list_rows.html", {
                "rows": [{"paper": paper, "approved_count": len(approved_claims), "latest_pkg": package}],
            })
        return _panel(f"Export failed: {exc}")

    if request.GET.get("from") == "list":
        return render(request, "export/partials/export_list_rows.html", {
            "rows": [{"paper": paper, "approved_count": len(approved_claims), "latest_pkg": package}],
        })
    return _panel()


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

    safe_name = (package.paper.doi or str(package.paper.pk)).replace("/", "_").replace(":", "_")
    try:
        f = package.annotated_pdf.open("rb")
    except (FileNotFoundError, OSError):
        logger.error("Export file missing for package %s", package_pk)
        return HttpResponse(
            "Export file not found — please regenerate the export.",
            status=404,
            content_type="text/plain",
        )

    log_action(request, package, AuditLog.Action.EXPORT,
               after={"package": package.pk})

    return FileResponse(
        f,
        content_type="application/pdf",
        as_attachment=True,
        filename=f"{safe_name}_annotated.pdf",
    )


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
