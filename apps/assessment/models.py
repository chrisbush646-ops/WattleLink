from django.conf import settings
from django.db import models

from apps.accounts.managers import TenantManager, UnfilteredManager
from apps.core.models import SoftDeleteModel


class GradeAssessment(SoftDeleteModel):
    class OverallRating(models.TextChoices):
        HIGH = "High", "High"
        MODERATE = "Moderate", "Moderate"
        LOW = "Low", "Low"
        VERY_LOW = "Very Low", "Very Low"

    class DomainRating(models.TextChoices):
        NOT_SERIOUS = "Not serious", "Not serious"
        SERIOUS = "Serious", "Serious"
        VERY_SERIOUS = "Very serious", "Very serious"
        UNDETECTED = "Undetected", "Undetected"
        SUSPECTED = "Suspected", "Suspected"
        NO_INFO = "No information", "No information"

    class Status(models.TextChoices):
        AI_DRAFT = "AI_DRAFT", "AI Draft"
        CONFIRMED = "CONFIRMED", "Confirmed"

    tenant = models.ForeignKey(
        "accounts.Tenant",
        on_delete=models.CASCADE,
        related_name="grade_assessments",
    )
    paper = models.OneToOneField(
        "literature.Paper",
        on_delete=models.CASCADE,
        related_name="grade_assessment",
    )
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.AI_DRAFT,
    )
    overall_rating = models.CharField(
        max_length=20,
        choices=OverallRating.choices,
        blank=True,
    )

    # Domain 1: Risk of Bias
    rob_rating = models.CharField(max_length=20, choices=DomainRating.choices, blank=True)
    rob_rationale = models.TextField(blank=True)
    rob_page_ref = models.CharField(max_length=100, blank=True)

    # Domain 2: Inconsistency
    inconsistency_rating = models.CharField(max_length=20, choices=DomainRating.choices, blank=True)
    inconsistency_rationale = models.TextField(blank=True)
    inconsistency_page_ref = models.CharField(max_length=100, blank=True)

    # Domain 3: Indirectness
    indirectness_rating = models.CharField(max_length=20, choices=DomainRating.choices, blank=True)
    indirectness_rationale = models.TextField(blank=True)
    indirectness_page_ref = models.CharField(max_length=100, blank=True)

    # Domain 4: Imprecision
    imprecision_rating = models.CharField(max_length=20, choices=DomainRating.choices, blank=True)
    imprecision_rationale = models.TextField(blank=True)
    imprecision_page_ref = models.CharField(max_length=100, blank=True)

    # Domain 5: Publication Bias
    publication_bias_rating = models.CharField(max_length=20, choices=DomainRating.choices, blank=True)
    publication_bias_rationale = models.TextField(blank=True)
    publication_bias_page_ref = models.CharField(max_length=100, blank=True)

    ai_prefilled = models.BooleanField(default=False)
    confirmed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="confirmed_grade_assessments",
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

    def __str__(self):
        return f"GRADE: {self.paper} — {self.overall_rating or 'unrated'}"

    @property
    def domains(self):
        """Return ordered list of (label, rating, rationale, page_ref) tuples."""
        return [
            ("Risk of Bias", self.rob_rating, self.rob_rationale, self.rob_page_ref),
            ("Inconsistency", self.inconsistency_rating, self.inconsistency_rationale, self.inconsistency_page_ref),
            ("Indirectness", self.indirectness_rating, self.indirectness_rationale, self.indirectness_page_ref),
            ("Imprecision", self.imprecision_rating, self.imprecision_rationale, self.imprecision_page_ref),
            ("Publication Bias", self.publication_bias_rating, self.publication_bias_rationale, self.publication_bias_page_ref),
        ]


class RobAssessment(SoftDeleteModel):
    """Cochrane Risk of Bias 2 (RoB 2) assessment — five fixed domains."""

    class Judgment(models.TextChoices):
        LOW = "Low", "Low"
        SOME_CONCERNS = "Some concerns", "Some concerns"
        HIGH = "High", "High"
        NO_INFORMATION = "No information", "No information"

    class Status(models.TextChoices):
        AI_DRAFT = "AI_DRAFT", "AI Draft"
        CONFIRMED = "CONFIRMED", "Confirmed"

    tenant = models.ForeignKey(
        "accounts.Tenant",
        on_delete=models.CASCADE,
        related_name="rob_assessments",
    )
    paper = models.OneToOneField(
        "literature.Paper",
        on_delete=models.CASCADE,
        related_name="rob_assessment",
    )
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.AI_DRAFT,
    )
    overall_judgment = models.CharField(
        max_length=20,
        choices=Judgment.choices,
        blank=True,
    )

    # Domain 1: Randomisation process
    d1_judgment = models.CharField(max_length=20, choices=Judgment.choices, blank=True)
    d1_rationale = models.TextField(blank=True)
    d1_page_ref = models.CharField(max_length=100, blank=True)

    # Domain 2: Deviations from intended interventions
    d2_judgment = models.CharField(max_length=20, choices=Judgment.choices, blank=True)
    d2_rationale = models.TextField(blank=True)
    d2_page_ref = models.CharField(max_length=100, blank=True)

    # Domain 3: Missing outcome data
    d3_judgment = models.CharField(max_length=20, choices=Judgment.choices, blank=True)
    d3_rationale = models.TextField(blank=True)
    d3_page_ref = models.CharField(max_length=100, blank=True)

    # Domain 4: Measurement of outcomes
    d4_judgment = models.CharField(max_length=20, choices=Judgment.choices, blank=True)
    d4_rationale = models.TextField(blank=True)
    d4_page_ref = models.CharField(max_length=100, blank=True)

    # Domain 5: Selection of the reported result
    d5_judgment = models.CharField(max_length=20, choices=Judgment.choices, blank=True)
    d5_rationale = models.TextField(blank=True)
    d5_page_ref = models.CharField(max_length=100, blank=True)

    ai_prefilled = models.BooleanField(default=False)
    confirmed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="confirmed_rob_assessments",
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

    def __str__(self):
        return f"RoB 2: {self.paper} — {self.overall_judgment or 'unassessed'}"

    ROB2_DOMAINS = [
        ("d1", "Randomisation process"),
        ("d2", "Deviations from intended interventions"),
        ("d3", "Missing outcome data"),
        ("d4", "Measurement of outcomes"),
        ("d5", "Selection of the reported result"),
    ]

    @property
    def domains(self):
        """Return ordered list of (prefix, label, judgment, rationale, page_ref)."""
        return [
            (prefix, label,
             getattr(self, f"{prefix}_judgment"),
             getattr(self, f"{prefix}_rationale"),
             getattr(self, f"{prefix}_page_ref"))
            for prefix, label in self.ROB2_DOMAINS
        ]
