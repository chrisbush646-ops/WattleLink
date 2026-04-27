from django.conf import settings
from django.db import models

from apps.accounts.managers import TenantManager, UnfilteredManager
from apps.core.models import SoftDeleteModel


class ExportPackage(SoftDeleteModel):
    """
    A point-in-time export of a paper's approved claims as an annotated PDF
    package ready for Veeva PromoMats submission.
    """
    class Status(models.TextChoices):
        PENDING = "PENDING", "Pending"
        PROCESSING = "PROCESSING", "Processing"
        READY = "READY", "Ready"
        FAILED = "FAILED", "Failed"

    tenant = models.ForeignKey(
        "accounts.Tenant",
        on_delete=models.CASCADE,
        related_name="export_packages",
    )
    paper = models.ForeignKey(
        "literature.Paper",
        on_delete=models.CASCADE,
        related_name="export_packages",
    )
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
    )
    annotated_pdf = models.FileField(
        upload_to="exports/annotated/",
        blank=True,
    )
    metadata_json = models.JSONField(
        default=dict,
        help_text="Snapshot of approved claims and paper metadata at export time.",
    )
    claim_count = models.PositiveIntegerField(default=0)
    error_message = models.TextField(blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="export_packages",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    objects = TenantManager()
    all_objects = UnfilteredManager()

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"Export #{self.pk} — {self.paper}"
