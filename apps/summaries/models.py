from django.conf import settings
from django.db import models

from apps.accounts.managers import TenantManager, UnfilteredManager
from apps.core.models import SoftDeleteModel


class PaperSummary(SoftDeleteModel):
    class Status(models.TextChoices):
        AI_DRAFT = "AI_DRAFT", "AI Draft"
        CONFIRMED = "CONFIRMED", "Confirmed"

    tenant = models.ForeignKey(
        "accounts.Tenant",
        on_delete=models.CASCADE,
        related_name="paper_summaries",
    )
    paper = models.OneToOneField(
        "literature.Paper",
        on_delete=models.CASCADE,
        related_name="summary",
    )
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.AI_DRAFT,
    )
    methodology = models.TextField(blank=True)
    executive_paragraph = models.TextField(blank=True)
    safety_summary = models.TextField(blank=True)
    adverse_events = models.JSONField(
        default=list,
        help_text="[{event, incidence, page_ref}, ...]",
    )
    limitations = models.JSONField(
        default=list,
        help_text="[{limitation, page_ref}, ...]",
    )
    ai_prefilled = models.BooleanField(default=False)
    confirmed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="confirmed_summaries",
    )
    confirmed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = TenantManager()
    all_objects = UnfilteredManager()

    class Meta:
        indexes = [
            models.Index(fields=["tenant", "status"]),
        ]
        verbose_name_plural = "paper summaries"

    def __str__(self):
        return f"Summary: {self.paper}"


class FindingsRow(models.Model):
    class Category(models.TextChoices):
        PRIMARY = "Primary", "Primary"
        SECONDARY = "Secondary", "Secondary"
        SAFETY = "Safety", "Safety"
        OTHER = "Other", "Other"

    summary = models.ForeignKey(
        PaperSummary,
        on_delete=models.CASCADE,
        related_name="findings",
    )
    category = models.CharField(
        max_length=20,
        choices=Category.choices,
        default=Category.PRIMARY,
    )
    finding = models.TextField()
    quantitative_result = models.CharField(max_length=300, blank=True)
    page_ref = models.CharField(max_length=100, blank=True)
    clinical_significance = models.TextField(blank=True)
    order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["order", "pk"]

    def __str__(self):
        return f"[{self.category}] {self.finding[:60]}"
