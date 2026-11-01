from django.db import transaction
from django.db.models import Count
from rest_framework.exceptions import NotFound

from ..models import StatsThread
from . import messages as msgs

MAX_LISTED = 50
MAX_STATE_BYTES = 4 * 1024 * 1024


def as_json(thread, with_state=False) -> dict:
    out = {
        "id": str(thread.id),
        "title": thread.title,
        "created_at": thread.created_at,
        "updated_at": thread.updated_at,
    }
    if with_state:
        state = {k: v for k, v in (thread.state or {}).items() if k != "messages"}
        out["state"] = {**state, "messages": msgs.ui_messages(thread)}
    return out


def recent(project, user) -> list:
    threads = (
        StatsThread.objects.filter(project=project, user=user)
        .only("id", "title", "created_at", "updated_at")
        .annotate(message_count=Count("messages"))[:MAX_LISTED]
    )
    return [{**as_json(t), "message_count": t.message_count} for t in threads]


def create(project, user, title) -> StatsThread:
    return StatsThread.objects.create(project=project, user=user, title=title, state={})


def save(thread, data) -> None:
    fields = ["updated_at"]
    if "state" in data:
        if msgs.size(data["state"]) > MAX_STATE_BYTES:
            raise msgs.invalid("state", msgs.TOO_LONG)
        thread.state = data["state"]
        fields.append("state")

    parsed = msgs.parse(data["message_ids"], data["messages"]) if "message_ids" in data else None

    if "title" in data:
        thread.title = data["title"]
        fields.append("title")

    with transaction.atomic():
        if not _lock(thread):
            raise NotFound("This chat is no longer here.")
        if parsed is not None:
            msgs.sync(thread, *parsed)
        thread.save(update_fields=fields)


def delete(thread) -> None:
    with transaction.atomic():
        if _lock(thread):
            thread.delete()


def _lock(thread) -> bool:
    return StatsThread.objects.select_for_update().filter(pk=thread.pk).only("id").first() is not None
