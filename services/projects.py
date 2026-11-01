from django.db import transaction
from django.db.models import Q
from rest_framework.exceptions import NotFound, PermissionDenied

from ..models import StatsProject
from . import messages as msgs

MAX_LISTED = 100
MAX_STATE_BYTES = 8 * 1024 * 1024
OWNER_ONLY = "Only the project's owner can do this."


class StateConflict(Exception):
    def __init__(self, project):
        super().__init__("This project was changed elsewhere. Reload to get the latest version.")
        self.current = {"version": project.version, "state": project.state}


def visible_to(user):
    return StatsProject.objects.filter(Q(user=user) | Q(collaborators=user)).distinct()


def get(user, project_id, *fields) -> StatsProject:
    qs = visible_to(user).filter(id=project_id)
    if fields:
        qs = qs.only("id", "user_id", *fields)
    project = qs.first()
    if project is None:
        raise NotFound("Project not found.")
    return project


def as_json(project, user, with_state=False) -> dict:
    out = {
        "id": project.id,
        "name": project.name,
        "version": project.version,
        "is_owner": project.user_id == user.id,
        "created_at": project.created_at,
        "updated_at": project.updated_at,
    }
    if with_state:
        out["state"] = project.state
    return out


def recent(user) -> list:
    rows = visible_to(user).only("id", "user_id", "name", "version", "created_at", "updated_at")[:MAX_LISTED]
    return [as_json(p, user) for p in rows]


def create(user, name) -> StatsProject:
    return StatsProject.objects.create(user=user, name=name, state={})


def rename(project, name) -> None:
    project.name = name
    project.save(update_fields=["name", "updated_at"])


def save_state(project, state, version) -> StatsProject:
    if msgs.size(state) > MAX_STATE_BYTES:
        raise msgs.invalid("state", "This project is too large to save.")
    with transaction.atomic():
        row = StatsProject.objects.select_for_update().filter(pk=project.pk).first()
        if row is None:
            raise NotFound("Project not found.")
        if row.version != version:
            raise StateConflict(row)
        row.state = state
        row.version = version + 1
        row.save(update_fields=["state", "version", "updated_at"])
    return row


def delete(project, user) -> None:
    if project.user_id != user.id:
        raise PermissionDenied(OWNER_ONLY)
    project.delete()
