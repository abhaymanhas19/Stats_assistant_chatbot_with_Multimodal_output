from django.contrib import admin

from .models import StatsMessage, StatsProject, StatsProjectFile, StatsThread


@admin.register(StatsProject)
class StatsProjectAdmin(admin.ModelAdmin):
    list_display = ("id", "name", "user", "version", "updated_at")
    search_fields = ("=id", "name", "user__email")
    raw_id_fields = ("user",)
    readonly_fields = ("created_at", "updated_at")


@admin.register(StatsProjectFile)
class StatsProjectFileAdmin(admin.ModelAdmin):
    list_display = ("id", "project", "name", "kind", "created_at")
    list_filter = ("kind",)
    search_fields = ("name", "=project__id")
    raw_id_fields = ("project", "file")
    readonly_fields = ("created_at",)


@admin.register(StatsThread)
class StatsThreadAdmin(admin.ModelAdmin):
    list_display = ("id", "project", "user", "title", "updated_at")
    search_fields = ("id", "title", "user__email", "=project__id")
    raw_id_fields = ("project", "user")
    readonly_fields = ("created_at", "updated_at")


@admin.register(StatsMessage)
class StatsMessageAdmin(admin.ModelAdmin):
    list_display = ("id", "thread", "message_id", "position", "role", "size", "updated_at")
    list_filter = ("role",)
    search_fields = ("message_id", "=thread__id")
    raw_id_fields = ("thread",)
    readonly_fields = ("created_at", "updated_at")
