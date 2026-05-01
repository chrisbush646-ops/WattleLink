from django.db import models

from apps.accounts.models import Tenant, User


class AISearchSession(models.Model):
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="ai_sessions")
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name="ai_sessions")
    title = models.CharField(max_length=300)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at"]

    def __str__(self):
        return self.title[:80]


class AISearchMessage(models.Model):
    class Role(models.TextChoices):
        USER = "user", "User"
        ASSISTANT = "assistant", "Assistant"

    session = models.ForeignKey(AISearchSession, on_delete=models.CASCADE, related_name="messages")
    role = models.CharField(max_length=10, choices=Role.choices)
    content = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]

    def __str__(self):
        return f"{self.role}: {self.content[:60]}"
