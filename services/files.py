import os

from django.http import FileResponse
from rest_framework.exceptions import NotFound

from apps.api.permission import require_file_access
from apps.users.models import Files

from ..models import StatsProjectFile
from .messages import invalid

MAX_FILES = 20
TOO_MANY = f"A project holds at most {MAX_FILES} files."


def as_json(row) -> dict:
    return {
        "id": row.id,
        "file_id": row.file_id,
        "name": row.name,
        "kind": row.kind,
        "sniff": row.sniff,
        "created_at": row.created_at,
    }


def listed(project) -> list:
    return [as_json(r) for r in project.files.all()]


def attach(request, project, file_id, kind) -> tuple[StatsProjectFile, bool]:
    file = Files.objects.filter(id=file_id).only("id", "file", "email").first()
    if file is None:
        raise NotFound("File not found.")
    require_file_access(request, file)
    existing = project.files.filter(file_id=file.id).first()
    if existing:
        return existing, False
    if project.files.count() >= MAX_FILES:
        raise invalid("file_id", TOO_MANY)
    row = StatsProjectFile.objects.create(
        project=project, file=file, kind=kind, name=os.path.basename(file.file.name)[:500]
    )
    return row, True


def set_sniff(project, row_id, sniff) -> StatsProjectFile:
    row = _row(project, row_id)
    row.sniff = sniff
    row.save(update_fields=["sniff"])
    return row


def detach(project, row_id) -> None:
    _row(project, row_id).delete()


def content(project, row_id) -> FileResponse:
    row = project.files.select_related("file").filter(id=row_id).first()
    if row is None:
        raise NotFound("File not found.")
    return FileResponse(row.file.file.open("rb"), as_attachment=False, filename=row.name)


def _row(project, row_id) -> StatsProjectFile:
    row = project.files.filter(id=row_id).first()
    if row is None:
        raise NotFound("File not found.")
    return row
