from django.conf import settings
from django.contrib.postgres.indexes import GinIndex
from django.contrib.postgres.search import SearchVectorField
from django.db import models

from apps.accounts.managers import TenantManager, UnfilteredManager
from apps.core.models import SoftDeleteModel


class Paper(SoftDeleteModel):
    class Status(models.TextChoices):
        AWAITING_UPLOAD = "AWAITING_UPLOAD", "Awaiting Upload"
        INGESTED = "INGESTED", "Ingested"
        ASSESSED = "ASSESSED", "Assessed"
        SUMMARISED = "SUMMARISED", "Summarised"
        CLAIMS_GENERATED = "CLAIMS_GENERATED", "Claims Generated"
        APPROVED = "APPROVED", "Approved"

    class Source(models.TextChoices):
        PUBMED_OA = "PUBMED_OA", "PubMed Open Access"
        PDF_UPLOAD = "PDF_UPLOAD", "PDF Upload"
        MANUAL = "MANUAL", "Manual Entry"

    class StudyType(models.TextChoices):
        RCT = "RCT", "RCT"
        META_ANALYSIS = "Meta-analysis", "Meta-analysis"
        SYSTEMATIC_REVIEW = "Systematic review", "Systematic Review"
        OBSERVATIONAL = "Observational", "Observational"
        OTHER = "Other", "Other"

    class GradeRating(models.TextChoices):
        HIGH = "High", "High"
        MODERATE = "Moderate", "Moderate"
        LOW = "Low", "Low"
        VERY_LOW = "Very Low", "Very Low"

    class DOISource(models.TextChoices):
        PUBMED = "PUBMED", "PubMed"
        CROSSREF = "CROSSREF", "CrossRef"
        USER_ENTRY = "USER_ENTRY", "User Entry"
        PDF_METADATA = "PDF_METADATA", "PDF Metadata"
        UNSET = "UNSET", "Not Set"

    tenant = models.ForeignKey(
        "accounts.Tenant",
        on_delete=models.CASCADE,
        related_name="papers",
    )
    title = models.TextField()
    authors = models.JSONField(default=list)
    journal = models.CharField(max_length=300)
    journal_short = models.CharField(max_length=100, blank=True)
    published_date = models.DateField(null=True, blank=True)
    volume = models.CharField(max_length=20, blank=True)
    issue = models.CharField(max_length=20, blank=True)
    pages = models.CharField(max_length=50, blank=True)
    doi = models.CharField(max_length=200, blank=True)
    pubmed_id = models.CharField(max_length=20, blank=True, db_index=True)
    pmcid = models.CharField(max_length=20, blank=True)
    study_type = models.CharField(max_length=20, choices=StudyType.choices, blank=True)
    source = models.CharField(
        max_length=20, choices=Source.choices, default=Source.PUBMED_OA
    )
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.INGESTED
    )
    grade_rating = models.CharField(
        max_length=10, choices=GradeRating.choices, blank=True
    )
    source_file = models.FileField(upload_to="papers/", blank=True)
    full_text = models.TextField(blank=True)
    search_vector = SearchVectorField(null=True, blank=True)
    doi_verified = models.BooleanField(default=False)
    doi_verified_at = models.DateTimeField(null=True, blank=True)
    doi_source = models.CharField(
        max_length=20,
        choices=DOISource.choices,
        default=DOISource.UNSET,
    )
    doi_verification_details = models.JSONField(default=dict, blank=True)
    safety_scanned_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = TenantManager()
    all_objects = UnfilteredManager()

    class Meta:
        ordering = ["-published_date", "-created_at"]
        indexes = [
            models.Index(fields=["tenant", "status"]),
            models.Index(fields=["tenant", "published_date"]),
            GinIndex(fields=["search_vector"], name="paper_search_vector_idx"),
        ]

    def __str__(self):
        return self.title[:80]

    def apa7_citation(self):
        year = self.published_date.year if self.published_date else "n.d."
        if isinstance(self.authors, list):
            authors = ", ".join(self.authors) if self.authors else "Unknown"
        else:
            authors = self.authors or "Unknown"
        vol = f", {self.volume}" if self.volume else ""
        issue = f"({self.issue})" if self.issue else ""
        pages = f", {self.pages}" if self.pages else ""
        doi = f" https://doi.org/{self.doi}" if (self.doi and self.doi_verified) else ""
        return f"{authors} ({year}). {self.title}. {self.journal}{vol}{issue}{pages}.{doi}"

    @property
    def is_open_access(self):
        return bool(self.pmcid) or self.source == self.Source.PUBMED_OA

    @property
    def authors_display(self):
        if isinstance(self.authors, list):
            return ", ".join(self.authors)
        return self.authors or ""

    @property
    def pipeline_stage(self):
        order = [
            self.Status.AWAITING_UPLOAD,
            self.Status.INGESTED,
            self.Status.ASSESSED,
            self.Status.SUMMARISED,
            self.Status.CLAIMS_GENERATED,
            self.Status.APPROVED,
        ]
        try:
            return order.index(self.status)
        except ValueError:
            return 0


class SavedSearch(models.Model):
    tenant = models.ForeignKey(
        "accounts.Tenant",
        on_delete=models.CASCADE,
        related_name="saved_searches",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="saved_searches",
    )
    name = models.CharField(max_length=200)
    query = models.TextField()
    filters = models.JSONField(default=dict)
    refinement_terms = models.JSONField(default=list)
    exclusion_terms = models.JSONField(default=list)
    result_count_history = models.JSONField(default=list)
    ai_suggestions_used = models.JSONField(default=list)
    last_run = models.DateTimeField(null=True, blank=True)
    result_count = models.IntegerField(default=0)
    last_result_pmids = models.JSONField(default=list)
    created_at = models.DateTimeField(auto_now_add=True)

    objects = TenantManager()
    all_objects = UnfilteredManager()

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.name
