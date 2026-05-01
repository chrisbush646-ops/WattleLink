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
    commercial_headline = models.TextField(
        blank=True,
        help_text="Plain-language headline for marketing/sales use. Data-anchored, no extrapolation.",
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
            "Keys: verbatim_data (bool), population_match (bool), endpoint_match (bool), "
            "no_extrapolation (bool), fair_balance_present (bool), approved_indication_only (bool). "
            "approved_indication_only: claim falls within the TGA-approved indication (MA Code req.)."
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

    # MA Code (21st ed.) / TGA Advertising Code compliance fields
    approved_indication = models.CharField(
        max_length=500,
        blank=True,
        help_text="TGA-approved indication this claim relates to. Must not exceed the approved indication.",
    )
    pi_version = models.CharField(
        max_length=100,
        blank=True,
        help_text="Product Information version/date this claim was verified against (e.g. 'v1.4 — March 2026').",
    )
    expires_at = models.DateField(
        null=True,
        blank=True,
        help_text="Date by which this claim must be reviewed for continued accuracy. MA Code requires periodic review.",
    )
    certified_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="certified_claims",
        help_text="Medical Lead (MD/PharmD) who certified this claim per MA Code §8.",
    )
    certified_at = models.DateTimeField(null=True, blank=True)

    # MLR compliance validation (Medicines Australia Code Ed. 19/20 + TGA)
    mlr_compliance_score = models.PositiveSmallIntegerField(
        null=True, blank=True,
        help_text="0-100 MA Code compliance score from AI MLR auditor.",
    )
    mlr_verdict = models.CharField(
        max_length=10, blank=True,
        help_text="PASS (80-100), WARN (50-79), or FAIL (0-49).",
    )
    mlr_red_flags = models.JSONField(default=list)
    mlr_rule_results = models.JSONField(
        default=dict,
        help_text="Per-rule breakdown: {rule: {pass, deduction, finding}}",
    )
    mlr_rationale = models.TextField(blank=True)
    mlr_checked_at = models.DateTimeField(null=True, blank=True)

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
            "approved_indication_only",   # MA Code / TGA requirement
        ]
        return all(self.fidelity_checklist.get(k) for k in required)

    @property
    def is_expired(self):
        from django.utils import timezone
        if self.expires_at is None:
            return False
        return self.expires_at < timezone.localdate()

    @property
    def is_certified(self):
        return self.certified_by_id is not None and self.certified_at is not None
