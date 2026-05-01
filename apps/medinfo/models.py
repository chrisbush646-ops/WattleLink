from django.conf import settings
from django.db import models

from apps.accounts.managers import TenantManager, UnfilteredManager
from apps.core.models import SoftDeleteModel


class Enquiry(SoftDeleteModel):
    class Source(models.TextChoices):
        HCP = "HCP", "Healthcare Professional"
        PATIENT = "PATIENT", "Patient / Carer"
        INTERNAL = "INTERNAL", "Internal"
        OTHER = "OTHER", "Other"

    class Status(models.TextChoices):
        OPEN = "OPEN", "Open"
        DRAFT = "DRAFT", "Draft Response"
        RESPONDED = "RESPONDED", "Responded"
        CLOSED = "CLOSED", "Closed"

    tenant = models.ForeignKey(
        "accounts.Tenant",
        on_delete=models.CASCADE,
        related_name="enquiries",
    )
    question = models.TextField()
    source = models.CharField(max_length=20, choices=Source.choices, default=Source.HCP)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.OPEN)
    response = models.TextField(blank=True)
    citations = models.JSONField(
        default=list,
        help_text="[{paper_id, apa7, page_ref}, ...]",
    )
    keywords = models.JSONField(default=list, help_text="AI-extracted keywords for trend analysis")
    assigned_to = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name="assigned_enquiries",
    )
    responded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name="responded_enquiries",
    )
    responded_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name="logged_enquiries",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = TenantManager()
    all_objects = UnfilteredManager()

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["tenant", "status"])]
        verbose_name_plural = "enquiries"

    def __str__(self):
        return self.question[:80]
