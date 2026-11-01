from unittest.mock import AsyncMock, patch

import pytest
from django.core.cache import cache
from django.test import Client
from rest_framework_simplejwt.tokens import RefreshToken

from apps.statsassistant.models import StatsProject
from apps.statsassistant.services import engine

PASSWORD = "StrongPass123"
BASE = "/api/v1/stats/projects/"

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def clean_cache(settings):
    settings.STATS_RUNNER_SECRET = "test-secret"
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def owner(django_user_model):
    return django_user_model.objects.create_user(email="owner@example.com", password=PASSWORD)


@pytest.fixture
def stranger(django_user_model):
    return django_user_model.objects.create_user(email="stranger@example.com", password=PASSWORD)


@pytest.fixture
def project(owner):
    return StatsProject.objects.create(user=owner, name="Survey 2026")


def bearer(user):
    return {"HTTP_AUTHORIZATION": f"Bearer {RefreshToken.for_user(user).access_token}"}


def post(user, url, body=None):
    headers = bearer(user) if user else {}
    return Client().post(url, body or {}, content_type="application/json", **headers)


@pytest.fixture
def runner():
    with patch.object(engine, "_send", new_callable=AsyncMock) as send:
        send.return_value = {"id": "s1", "host": "10.0.0.5:8080"}
        yield send


def test_needs_a_token(project, runner):
    assert post(None, f"{BASE}{project.id}/engine/session/").status_code == 401
    runner.assert_not_called()


def test_other_users_project_is_not_found(project, stranger, runner):
    assert post(stranger, f"{BASE}{project.id}/engine/session/").status_code == 404
    runner.assert_not_called()


def test_run_code_without_a_session_is_gone(project, owner, runner):
    res = post(owner, f"{BASE}{project.id}/engine/run-code/", {"code": "1"})
    assert res.status_code == 410
    runner.assert_not_called()


def test_session_then_run_code_goes_to_the_sessions_pod(project, owner, runner):
    assert post(owner, f"{BASE}{project.id}/engine/session/").status_code == 200
    runner.return_value = {"ok": True, "result": {"ok": True, "value": 1000}}
    res = post(owner, f"{BASE}{project.id}/engine/run-code/", {"code": "len(data['d1'])", "timeout_ms": 5000})
    assert res.status_code == 200
    assert res.json() == {"result": {"ok": True, "value": 1000}}
    host, method, target, _ = runner.call_args.args
    assert (host, method, target) == ("10.0.0.5:8080", "POST", "/sessions/s1/op")
    assert runner.call_args.kwargs["payload"] == {"op": "run_code", "code": "len(data['d1'])", "read_only": True, "timeout": 5.0}


def test_unknown_call_is_rejected(project, owner, runner):
    post(owner, f"{BASE}{project.id}/engine/session/")
    res = post(owner, f"{BASE}{project.id}/engine/call/", {"fn": "restore", "args": []})
    assert res.status_code == 400
    assert runner.call_count == 1


def test_one_running_call_per_user(project, owner, runner):
    post(owner, f"{BASE}{project.id}/engine/session/")
    cache.add(f"stats-engine-busy:{owner.id}", 1, 60)
    res = post(owner, f"{BASE}{project.id}/engine/run-code/", {"code": "1"})
    assert res.status_code == 429


def test_timeout_forgets_the_session(project, owner, runner):
    post(owner, f"{BASE}{project.id}/engine/session/")
    runner.side_effect = engine.EngineError(504, "The analysis took too long and was stopped.")
    assert post(owner, f"{BASE}{project.id}/engine/run-code/", {"code": "1"}).status_code == 504
    runner.side_effect = None
    assert post(owner, f"{BASE}{project.id}/engine/run-code/", {"code": "1"}).status_code == 410


def test_daily_budget(project, owner, runner, settings):
    settings.STATS_ENGINE_DAILY_SECONDS = 0
    post(owner, f"{BASE}{project.id}/engine/session/")
    assert post(owner, f"{BASE}{project.id}/engine/run-code/", {"code": "1"}).status_code == 429
