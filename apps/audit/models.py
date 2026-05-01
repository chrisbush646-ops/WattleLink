from django.db import models
from django.conf import settings
from apps.accounts.managers import TenantManager


class AuditLog(models.Model):
    class Action(models.TextChoices):
        CREATE = "CREATE"
        UPDATE = "UPDATE"
        APPROVE = "APPROVE"
        REJECT = "REJECT"
        EXPORT = "EXPORT"
        DELETE = "DELETE"
        AI_DRAFT = "AI_DRAFT"
        INGEST = "INGEST"

    tenant = models.ForeignKey(
        "accounts.Tenant",
        on_delete=models.CASCADE,
        related_name="audit_logs",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        on_delete=models.SET_NULL,
        related_name="audit_logs",
    )
    entity_type = models.CharField(max_length=50)
    entity_id = models.IntegerField()
    action = models.CharField(max_length=20, choices=Action.choices)
    before_state = models.JSONField(null=True, blank=True)
    after_state = models.JSONField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    objects = TenantManager()

    class Meta:
        indexes = [
            models.Index(fields=["tenant", "entity_type", "entity_id"]),
            models.Index(fields=["tenant", "created_at"]),
        ]
        ordering = ["-created_at"]

    def save(self, *args, **kwargs):
        if self.pk:
            raise ValueError("AuditLog records cannot be updated")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValueError("AuditLog records cannot be deleted")

    def __str__(self):
        return f"{self.action} {self.entity_type}#{self.entity_id} by {self.user_id}"
