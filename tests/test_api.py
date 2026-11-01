import pytest
from django.core.files.base import ContentFile
from rest_framework.test import APIClient

from apps.statsassistant.models import StatsCollaborator, StatsMessage, StatsProject, StatsThread
from apps.users.models import Files

PASSWORD = "StrongPass123"
BASE = "/api/v1/stats/projects/"

pytestmark = pytest.mark.django_db


@pytest.fixture
def owner(django_user_model):
    return django_user_model.objects.create_user(email="owner@example.com", password=PASSWORD)


@pytest.fixture
def collaborator(django_user_model):
    return django_user_model.objects.create_user(email="collab@example.com", password=PASSWORD)


@pytest.fixture
def stranger(django_user_model):
    return django_user_model.objects.create_user(email="stranger@example.com", password=PASSWORD)


@pytest.fixture
def client():
    return APIClient()


@pytest.fixture
def project(owner, collaborator):
    p = StatsProject.objects.create(user=owner, name="Survey 2026")
    StatsCollaborator.objects.create(project=p, user=collaborator, shared_by=owner)
    return p


def msg(mid, role="user", text="hi"):
    return {"id": mid, "role": role, "parts": [{"type": "text", "text": text}]}


def test_create_and_list(client, owner):
    client.force_authenticate(user=owner)
    r = client.post(BASE, {"name": "  Patients  "}, format="json")
    assert r.status_code == 201
    assert r.data["name"] == "Patients" and r.data["version"] == 0 and r.data["state"] == {}
    assert [p["name"] for p in client.get(BASE).data["projects"]] == ["Patients"]


def test_stranger_cannot_see_project(client, project, stranger):
    client.force_authenticate(user=stranger)
    assert client.get(f"{BASE}{project.id}/").status_code == 404
    assert client.put(f"{BASE}{project.id}/state/", {"state": {}, "version": 0}, format="json").status_code == 404
    assert client.get(BASE).data["projects"] == []


def test_collaborator_reads_but_cannot_delete(client, project, collaborator):
    client.force_authenticate(user=collaborator)
    r = client.get(f"{BASE}{project.id}/")
    assert r.status_code == 200 and r.data["is_owner"] is False
    assert client.delete(f"{BASE}{project.id}/").status_code == 403
    assert StatsProject.objects.filter(id=project.id).exists()


def test_state_save_checks_version(client, project, owner):
    client.force_authenticate(user=owner)
    url = f"{BASE}{project.id}/state/"
    r = client.put(url, {"state": {"recipe": [1]}, "version": 0}, format="json")
    assert r.status_code == 200 and r.data["version"] == 1
    stale = client.put(url, {"state": {"recipe": [2]}, "version": 0}, format="json")
    assert stale.status_code == 409
    assert stale.data["version"] == 1 and stale.data["state"] == {"recipe": [1]}


def test_thread_messages_are_stored_and_synced(client, project, owner):
    client.force_authenticate(user=owner)
    threads_url = f"{BASE}{project.id}/threads/"
    thread_id = client.post(threads_url, {"title": "First"}, format="json").data["id"]
    url = f"{threads_url}{thread_id}/"

    r = client.put(url, {"message_ids": ["a", "b"], "messages": [msg("a"), msg("b", "assistant", "hello")]}, format="json")
    assert r.status_code == 200
    r = client.put(url, {"message_ids": ["b", "c"], "messages": [msg("c")]}, format="json")
    assert r.status_code == 200

    rows = list(StatsMessage.objects.filter(thread_id=thread_id).values_list("message_id", "position"))
    assert rows == [("b", 0), ("c", 1)]
    page = client.get(f"{url}messages/").data
    assert page["total"] == 2 and [m["id"] for m in page["messages"]] == ["b", "c"]

    missing = client.put(url, {"message_ids": ["b", "c", "zz"], "messages": []}, format="json")
    assert missing.status_code == 409 and missing.data["missing"] == ["zz"]


def test_threads_are_private_to_their_user(client, project, owner, collaborator):
    thread = StatsThread.objects.create(project=project, user=owner, title="Mine")
    client.force_authenticate(user=collaborator)
    assert client.get(f"{BASE}{project.id}/threads/{thread.id}/").status_code == 404
    assert client.get(f"{BASE}{project.id}/threads/").data["threads"] == []


def test_attach_file_requires_its_uploader(client, project, owner, collaborator, settings):
    settings.STORAGES = {**settings.STORAGES, "default": {"BACKEND": "django.core.files.storage.InMemoryStorage"}}
    f = Files.objects.create(email=owner.email)
    f.file.save("survey.csv", ContentFile(b"a,b\n1,2\n"), save=True)

    client.force_authenticate(user=collaborator)
    assert client.post(f"{BASE}{project.id}/files/", {"file_id": f.id, "kind": "data"}, format="json").status_code == 403

    client.force_authenticate(user=owner)
    r = client.post(f"{BASE}{project.id}/files/", {"file_id": f.id, "kind": "data"}, format="json")
    assert r.status_code == 201 and r.data["name"] == "survey.csv"
    again = client.post(f"{BASE}{project.id}/files/", {"file_id": f.id, "kind": "data"}, format="json")
    assert again.status_code == 200 and again.data["id"] == r.data["id"]

    client.force_authenticate(user=collaborator)
    body = client.get(f"{BASE}{project.id}/files/{r.data['id']}/content/")
    assert body.status_code == 200 and b"".join(body.streaming_content) == b"a,b\n1,2\n"
