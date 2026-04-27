from django.conf import settings
from django.db import models

from apps.accounts.managers import TenantManager, UnfilteredManager
from apps.core.models import SoftDeleteModel


class CoreClaim(SoftDeleteModel):
    class Status(models.TextChoices):
        AI_DRAFT = "AI_DRAFT", "AI Draft"
        IN_REVIEW = "IN_REVIEW", "In Review"
        APPROVED = "APPROVED", "Approved"
        REJECTED = "REJECTED", "Rejected"

    class EndpointType(models.TextChoices):
        PRIMARY = "PRIMARY", "Primary"
        SECONDARY = "SECONDARY", "Secondary"
        SAFETY = "SAFETY", "Safety"
        OTHER = "OTHER", "Other"

    tenant = models.ForeignKey(
        "accounts.Tenant",
        on_delete=models.CASCADE,
        related_name="claims",
    )
    paper = models.ForeignKey(
        "literature.Paper",
        on_delete=models.CASCADE,
        related_name="claims",
    )
    claim_text = models.TextField()
    endpoint_type = models.CharField(
        max_length=20,
        choices=EndpointType.choices,
        default=EndpointType.PRIMARY,
    )
    source_passage = models.TextField(blank=True)
    source_reference = models.CharField(max_length=200, blank=True)

    fair_balance = models.TextField(blank=True)
    fair_balance_reference = models.CharField(max_length=200, blank=True)

    fidelity_checklist = models.JSONField(
        default=dict,
        help_text=(
            "Keys: verbatim_data (bool), population_match (bool), "
            "endpoint_match (bool), no_extrapolation (bool), fair_balance_present (bool)"
        ),
    )

    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.AI_DRAFT,
    )
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="reviewed_claims",
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    rejection_reason = models.TextField(blank=True)

    version = models.PositiveIntegerField(default=1)
    veeva_mat_id = models.CharField(max_length=30, blank=True)

    ai_generated = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = TenantManager()
    all_objects = UnfilteredManager()

    class Meta:
        ordering = ["endpoint_type", "created_at"]
        indexes = [
            models.Index(fields=["tenant", "status"]),
            models.Index(fields=["tenant", "paper"]),
        ]

    def __str__(self):
        return self.claim_text[:80]

    @property
    def fidelity_complete(self):
        required = [
            "verbatim_data",
            "population_match",
            "endpoint_match",
            "no_extrapolation",
            "fair_balance_present",
        ]
        return all(self.fidelity_checklist.get(k) for k in required)
