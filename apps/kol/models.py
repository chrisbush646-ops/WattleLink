from django.conf import settings
from django.db import models

from apps.accounts.managers import TenantManager, UnfilteredManager
from apps.core.models import SoftDeleteModel


class KOL(SoftDeleteModel):
    class Status(models.TextChoices):
        CANDIDATE = "CANDIDATE", "Candidate"
        ACTIVE = "ACTIVE", "Active"
        INACTIVE = "INACTIVE", "Inactive"

    tenant = models.ForeignKey(
        "accounts.Tenant",
        on_delete=models.CASCADE,
        related_name="kols",
    )
    name = models.CharField(max_length=300)
    institution = models.CharField(max_length=300, blank=True)
    specialty = models.CharField(max_length=200, blank=True)
    tier = models.PositiveSmallIntegerField(
        default=3,
        help_text="1 = highest influence, 5 = lowest",
    )
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.CANDIDATE,
    )
    email = models.EmailField(blank=True)
    linkedin = models.URLField(blank=True)
    location = models.CharField(max_length=200, blank=True)
    bio = models.TextField(blank=True)
    notes = models.TextField(blank=True, help_text="Internal MSL notes")
    ai_generated = models.BooleanField(default=False)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name="created_kols",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = TenantManager()
    all_objects = UnfilteredManager()

    class Meta:
        ordering = ["tier", "name"]
        indexes = [
            models.Index(fields=["tenant", "status"]),
            models.Index(fields=["tenant", "tier"]),
        ]

    def __str__(self):
        return self.name


class KOLPaperLink(models.Model):
    kol = models.ForeignKey(KOL, on_delete=models.CASCADE, related_name="paper_links")
    paper = models.ForeignKey(
        "literature.Paper",
        on_delete=models.CASCADE,
        related_name="kol_links",
    )
    relevance_note = models.TextField(blank=True)
    is_author = models.BooleanField(default=False)
    linked_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-linked_at"]
        unique_together = [("kol", "paper")]

    def __str__(self):
        return f"{self.kol.name} ↔ {self.paper}"


class KOLTalkingPoint(models.Model):
    kol = models.ForeignKey(KOL, on_delete=models.CASCADE, related_name="talking_points")
    text = models.TextField()
    source_note = models.CharField(max_length=300, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name="kol_talking_points",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]

    def __str__(self):
        return self.text[:80]


class KOLCandidate(models.Model):
    """An AI-suggested KOL awaiting human review before being added to the directory."""

    class Status(models.TextChoices):
        PENDING = "PENDING", "Pending Review"
        ACCEPTED = "ACCEPTED", "Accepted"
        REJECTED = "REJECTED", "Rejected"
        ON_HOLD = "ON_HOLD", "On Hold"

    class VerificationStatus(models.TextChoices):
        UNVERIFIED = "UNVERIFIED", "Checking…"
        LIKELY_CURRENT = "LIKELY_CURRENT", "Likely Current"
        UNCERTAIN = "UNCERTAIN", "Uncertain"
        POSSIBLY_INACTIVE = "POSSIBLY_INACTIVE", "Possibly Inactive"

    tenant = models.ForeignKey(
        "accounts.Tenant",
        on_delete=models.CASCADE,
        related_name="kol_candidates",
    )
    paper = models.ForeignKey(
        "literature.Paper",
        null=True, blank=True,
        on_delete=models.CASCADE,
        related_name="kol_candidates",
    )
    search_query = models.CharField(
        max_length=400, blank=True,
        help_text="Keyword query used to discover this candidate (blank for paper-extracted ones).",
    )

    # AI-extracted profile
    name = models.CharField(max_length=300)
    institution = models.CharField(max_length=300, blank=True)
    specialty = models.CharField(max_length=200, blank=True)
    tier = models.PositiveSmallIntegerField(default=3)
    location = models.CharField(max_length=200, blank=True)
    bio = models.TextField(blank=True)
    relevance_note = models.TextField(blank=True)
    is_author = models.BooleanField(default=False)

    # Currency verification (second AI pass)
    verification_status = models.CharField(
        max_length=20,
        choices=VerificationStatus.choices,
        default=VerificationStatus.UNVERIFIED,
    )
    verification_note = models.TextField(blank=True)
    verification_concerns = models.JSONField(default=list, blank=True)
    verified_at = models.DateTimeField(null=True, blank=True)

    # Human review workflow
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
    )
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name="reviewed_kol_candidates",
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    rejection_reason = models.TextField(blank=True)
    hold_reason = models.TextField(blank=True)

    # Link to accepted KOL once accepted
    kol = models.ForeignKey(
        KOL,
        null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name="source_candidates",
    )

    created_at = models.DateTimeField(auto_now_add=True)

    objects = TenantManager()
    all_objects = UnfilteredManager()

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["tenant", "status"]),
            models.Index(fields=["tenant", "paper"]),
        ]

    def __str__(self):
        return f"{self.name} (candidate)"

    @property
    def verification_color(self):
        return {
            self.VerificationStatus.LIKELY_CURRENT: "euc",
            self.VerificationStatus.UNCERTAIN: "wattle",
            self.VerificationStatus.POSSIBLY_INACTIVE: "coral",
            self.VerificationStatus.UNVERIFIED: "muted",
        }.get(self.verification_status, "muted")
