from django.conf import settings
from django.db import models

from apps.accounts.managers import TenantManager, UnfilteredManager
from apps.core.models import SoftDeleteModel


class SafetySignal(SoftDeleteModel):
    class Severity(models.TextChoices):
        CRITICAL = "CRITICAL", "Critical"
        SERIOUS = "SERIOUS", "Serious"
        MODERATE = "MODERATE", "Moderate"
        MILD = "MILD", "Mild"

    class Status(models.TextChoices):
        ACTIVE = "ACTIVE", "Active"
        MONITORING = "MONITORING", "Monitoring"
        CLOSED = "CLOSED", "Closed"

    tenant = models.ForeignKey(
        "accounts.Tenant",
        on_delete=models.CASCADE,
        related_name="safety_signals",
    )
    event_name = models.CharField(max_length=200)
    severity = models.CharField(
        max_length=20,
        choices=Severity.choices,
        default=Severity.MODERATE,
    )
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.ACTIVE,
    )
    description = models.TextField(blank=True)
    prepared_response = models.TextField(
        blank=True,
        help_text="MSL-ready talking point for this signal.",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="created_signals",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = TenantManager()
    all_objects = UnfilteredManager()

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["tenant", "status"]),
            models.Index(fields=["tenant", "severity"]),
        ]

    def __str__(self):
        return self.event_name

    @property
    def mention_count(self):
        return self.mentions.count()


class SignalMention(models.Model):
    signal = models.ForeignKey(
        SafetySignal,
        on_delete=models.CASCADE,
        related_name="mentions",
    )
    paper = models.ForeignKey(
        "literature.Paper",
        on_delete=models.CASCADE,
        related_name="signal_mentions",
    )
    incidence_treatment = models.CharField(max_length=100, blank=True)
    incidence_control = models.CharField(max_length=100, blank=True)
    passage = models.TextField(blank=True)
    page_ref = models.CharField(max_length=100, blank=True)
    added_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="signal_mentions",
    )
    added_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-added_at"]
        unique_together = [("signal", "paper")]

    def __str__(self):
        return f"{self.signal.event_name} — {self.paper}"
