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
    methodology = models.JSONField(default=dict, blank=True)
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
    validation_warnings = models.JSONField(default=list, blank=True)
    confidence_flags = models.JSONField(default=list, blank=True)
    preprocessing_stats = models.JSONField(default=dict, blank=True)
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

    @property
    def methodology_brief(self) -> str:
        """One-line plain text summary of the methodology for commercial view and compact displays."""
        m = self.methodology
        if not isinstance(m, dict):
            return str(m) if m else ""
        parts = []
        design = (m.get("study_design") or "").strip()
        if design and design.lower() != "not reported":
            parts.append(design)
        pop = m.get("population") or {}
        n = (pop.get("sample_size") or "").strip() if isinstance(pop, dict) else ""
        if n and n.lower() != "not reported":
            parts.append(n)
        followup = (m.get("follow_up") or "").strip()
        if followup and followup.lower() != "not reported":
            parts.append(f"{followup} follow-up")
        return " · ".join(parts)

    def __str__(self):
        return f"Summary: {self.paper}"


class FindingsRow(models.Model):
    class Category(models.TextChoices):
        PRIMARY = "Primary", "Primary"
        SECONDARY = "Secondary", "Secondary"
        POST_HOC = "Post-hoc", "Post-hoc"
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
