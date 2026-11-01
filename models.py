import uuid

from django.conf import settings
from django.db import models

from apps.users.models import Files


class StatsProject(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="stats_projects")
    name = models.CharField(max_length=200)
    state = models.JSONField(default=dict, blank=True)
    version = models.PositiveIntegerField(default=0)
    collaborators = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        through="StatsCollaborator",
        through_fields=("project", "user"),
        related_name="shared_stats_projects",
        blank=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [models.Index(fields=["user", "-updated_at"])]
        ordering = ["-updated_at"]

    def __str__(self):
        return f"{self.user_id}:{self.name or self.id}"


class StatsCollaborator(models.Model):
    project = models.ForeignKey(StatsProject, on_delete=models.CASCADE)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    shared_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )

    class Meta:
        constraints = [models.UniqueConstraint(fields=["project", "user"], name="stats_collaborator_unique")]


class StatsProjectFile(models.Model):
    KINDS = (("data", "Data"), ("document", "Document"))

    project = models.ForeignKey(StatsProject, on_delete=models.CASCADE, related_name="files")
    file = models.ForeignKey(Files, on_delete=models.CASCADE, related_name="+")
    kind = models.CharField(max_length=16, choices=KINDS)
    name = models.CharField(max_length=500)
    sniff = models.JSONField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["project", "file"], name="stats_project_file_unique")]
        ordering = ["created_at"]

    def __str__(self):
        return f"{self.project_id}:{self.name}"


class StatsThread(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    project = models.ForeignKey(StatsProject, on_delete=models.CASCADE, related_name="threads")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="stats_threads")
    title = models.CharField(max_length=200, blank=True, default="")
    state = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [models.Index(fields=["project", "user", "-updated_at"])]
        ordering = ["-updated_at"]

    def __str__(self):
        return f"{self.project_id}:{self.user_id}:{self.title or self.id}"


class StatsMessage(models.Model):
    thread = models.ForeignKey(StatsThread, on_delete=models.CASCADE, related_name="messages")
    message_id = models.CharField(max_length=200)
    position = models.PositiveIntegerField()
    role = models.CharField(max_length=16)
    parts = models.JSONField(default=list, blank=True)
    metadata = models.JSONField(null=True, blank=True)
    size = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["thread", "message_id"], name="stats_message_unique_id")]
        indexes = [models.Index(fields=["thread", "position"])]
        ordering = ["position"]

    def __str__(self):
        return f"{self.thread_id}:{self.position}:{self.role}"
