from django.utils import timezone

from apps.projectassistant.services.messages import (
    MAX_THREAD_BYTES,
    TOO_LONG,
    MissingMessages,
    invalid,
    parse,
    size,
)

from ..models import StatsMessage

__all__ = ["MissingMessages", "as_ui", "invalid", "parse", "size", "sync", "ui_messages", "TOO_LONG"]


def as_ui(row: StatsMessage) -> dict:
    out = {"id": row.message_id, "role": row.role, "parts": row.parts}
    if row.metadata is not None:
        out["metadata"] = row.metadata
    return out


def ui_messages(thread) -> list:
    return [as_ui(m) for m in thread.messages.all()]


def sync(thread, ids, by_id):
    rows = {m.message_id: m for m in thread.messages.only("id", "message_id", "position", "size")}
    missing = [i for i in ids if i not in rows and i not in by_id]
    if missing:
        raise MissingMessages(missing)
    position = {mid: n for n, mid in enumerate(ids)}
    kept = sum(row.size for mid, row in rows.items() if mid in position and mid not in by_id)
    if kept + sum(n for _, n in by_id.values()) > MAX_THREAD_BYTES:
        raise invalid("messages", TOO_LONG)
    gone = [row.id for mid, row in rows.items() if mid not in position]
    if gone:
        StatsMessage.objects.filter(id__in=gone).delete()
    now = timezone.now()
    created, updated, moved = [], [], []
    for mid, (m, n) in by_id.items():
        row = rows.get(mid)
        fields = {"position": position[mid], "role": m["role"], "parts": m["parts"], "metadata": m.get("metadata"), "size": n}
        if row is None:
            created.append(StatsMessage(thread=thread, message_id=mid, **fields))
            continue
        for name, value in fields.items():
            setattr(row, name, value)
        row.updated_at = now
        updated.append(row)
    for mid, row in rows.items():
        if mid in position and mid not in by_id and row.position != position[mid]:
            row.position = position[mid]
            moved.append(row)
    if updated:
        StatsMessage.objects.bulk_update(
            updated, ["position", "role", "parts", "metadata", "size", "updated_at"], batch_size=100
        )
    if moved:
        StatsMessage.objects.bulk_update(moved, ["position"], batch_size=500)
    if created:
        StatsMessage.objects.bulk_create(created, batch_size=100)
