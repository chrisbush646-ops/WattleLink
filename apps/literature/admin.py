from django.contrib import admin
from .models import Paper, SavedSearch


@admin.register(Paper)
class PaperAdmin(admin.ModelAdmin):
    list_display = ["title", "journal", "published_date", "status", "grade_rating", "tenant"]
    list_filter = ["status", "study_type", "source", "grade_rating", "tenant"]
    search_fields = ["title", "doi", "pubmed_id"]
    readonly_fields = ["search_vector", "created_at", "updated_at"]


@admin.register(SavedSearch)
class SavedSearchAdmin(admin.ModelAdmin):
    list_display = ["name", "user", "tenant", "last_run", "result_count"]
    list_filter = ["tenant"]
    search_fields = ["name", "query"]
