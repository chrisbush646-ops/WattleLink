from django.conf import settings
from django.db import models

from apps.accounts.managers import TenantManager, UnfilteredManager


class LiteratureReview(models.Model):
    tenant = models.ForeignKey(
        "accounts.Tenant",
        on_delete=models.CASCADE,
        related_name="literature_reviews",
    )
    title = models.CharField(max_length=300)
    content = models.TextField()
    papers = models.ManyToManyField(
        "literature.Paper",
        blank=True,
        related_name="literature_reviews",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="literature_reviews",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = TenantManager()
    all_objects = UnfilteredManager()

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.title
