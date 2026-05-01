from django.conf import settings
from django.db import models

from apps.accounts.managers import TenantManager, UnfilteredManager
from apps.core.models import SoftDeleteModel


class Conference(SoftDeleteModel):
    class Status(models.TextChoices):
        UPCOMING = "UPCOMING", "Upcoming"
        ATTENDED = "ATTENDED", "Attended"
        CANCELLED = "CANCELLED", "Cancelled"

    tenant = models.ForeignKey("accounts.Tenant", on_delete=models.CASCADE, related_name="conferences")
    name = models.CharField(max_length=300)
    location = models.CharField(max_length=200, blank=True)
    start_date = models.DateField()
    end_date = models.DateField(null=True, blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.UPCOMING)
    notes = models.TextField(blank=True)
    kols = models.ManyToManyField("kol.KOL", blank=True, related_name="conferences")
    papers = models.ManyToManyField("literature.Paper", blank=True, related_name="conferences")
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="created_conferences",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = TenantManager()
    all_objects = UnfilteredManager()

    class Meta:
        ordering = ["start_date"]

    def __str__(self):
        return self.name


class RoundTable(SoftDeleteModel):
    tenant = models.ForeignKey("accounts.Tenant", on_delete=models.CASCADE, related_name="round_tables")
    name = models.CharField(max_length=300)
    date = models.DateField()
    location = models.CharField(max_length=200, blank=True)
    discussion_themes = models.JSONField(default=list, help_text="List of theme strings")
    notes = models.TextField(blank=True)
    kols = models.ManyToManyField("kol.KOL", blank=True, related_name="round_tables")
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="created_round_tables",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = TenantManager()
    all_objects = UnfilteredManager()

    class Meta:
        ordering = ["date"]

    def __str__(self):
        return self.name


class AdvisoryBoard(SoftDeleteModel):
    tenant = models.ForeignKey("accounts.Tenant", on_delete=models.CASCADE, related_name="advisory_boards")
    name = models.CharField(max_length=300)
    date = models.DateField()
    location = models.CharField(max_length=200, blank=True)
    agenda_items = models.JSONField(default=list, help_text="List of agenda item strings")
    notes = models.TextField(blank=True)
    kols = models.ManyToManyField("kol.KOL", blank=True, related_name="advisory_boards")
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="created_advisory_boards",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = TenantManager()
    all_objects = UnfilteredManager()

    class Meta:
        ordering = ["date"]

    def __str__(self):
        return self.name


class OtherEvent(SoftDeleteModel):
    tenant = models.ForeignKey("accounts.Tenant", on_delete=models.CASCADE, related_name="other_events")
    name = models.CharField(max_length=300)
    date = models.DateField()
    location = models.CharField(max_length=200, blank=True)
    event_type = models.CharField(max_length=100, blank=True, help_text="e.g. Webinar, Workshop, Symposium")
    notes = models.TextField(blank=True)
    kols = models.ManyToManyField("kol.KOL", blank=True, related_name="other_events")
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="created_other_events",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = TenantManager()
    all_objects = UnfilteredManager()

    class Meta:
        ordering = ["date"]

    def __str__(self):
        return self.name
