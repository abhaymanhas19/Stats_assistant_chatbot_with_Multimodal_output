import json
from functools import wraps

from asgiref.sync import sync_to_async
from django.conf import settings
from django.http import JsonResponse, StreamingHttpResponse
from django.shortcuts import get_object_or_404
from django.views.decorators.csrf import csrf_exempt
from rest_framework import status
from rest_framework.exceptions import APIException, NotAuthenticated, ParseError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import StatsThread
from rest_framework_simplejwt.authentication import JWTAuthentication

from apps.projectassistant.chat.stream import HEADERS, stream_reply
from apps.projectassistant.serializers import problems

from .serializers import (
    ChatRequestSerializer,
    EngineCallSerializer,
    EngineCodeSerializer,
    EngineFileSerializer,
    EngineSessionSerializer,
    EngineSnapshotSerializer,
    EngineStepSerializer,
    FileAttachSerializer,
    FileSniffSerializer,
    MessagePageQuerySerializer,
    ProjectCreateSerializer,
    ProjectRenameSerializer,
    StateSaveSerializer,
    ThreadCreateSerializer,
    ThreadSaveSerializer,
    validated,
)
from .services import chat
from .services import engine
from .services import files
from .services import messages as msgs
from .services import projects
from .services import threads


def _paged(key, items, total, offset):
    end = offset + len(items)
    return {"total": total, "offset": offset, "next_offset": end if end < total else None, key: items}


class _StatsView(APIView):
    permission_classes = [IsAuthenticated]

    def project(self, request, project_id, *fields):
        return projects.get(request.user, project_id, *fields)


class ProjectListView(_StatsView):
    def get(self, request):
        return Response({"projects": projects.recent(request.user)})

    def post(self, request):
        payload = validated(ProjectCreateSerializer, request.data)
        project = projects.create(request.user, payload["name"])
        return Response(projects.as_json(project, request.user, with_state=True), status=status.HTTP_201_CREATED)


class ProjectDetailView(_StatsView):
    def get(self, request, project_id):
        project = self.project(request, project_id)
        return Response({
            **projects.as_json(project, request.user, with_state=True),
            "files": files.listed(project),
        })

    def patch(self, request, project_id):
        project = self.project(request, project_id)
        payload = validated(ProjectRenameSerializer, request.data)
        projects.rename(project, payload["name"])
        return Response(projects.as_json(project, request.user))

    def delete(self, request, project_id):
        projects.delete(self.project(request, project_id, "name"), request.user)
        return Response(status=status.HTTP_204_NO_CONTENT)


class ProjectStateView(_StatsView):
    def put(self, request, project_id):
        project = self.project(request, project_id, "version")
        payload = validated(StateSaveSerializer, request.data)
        try:
            saved = projects.save_state(project, payload["state"], payload["version"])
        except projects.StateConflict as e:
            return Response({"message": str(e), **e.current}, status=status.HTTP_409_CONFLICT)
        return Response({"version": saved.version, "updated_at": saved.updated_at})


class ProjectFilesView(_StatsView):
    def get(self, request, project_id):
        return Response({"files": files.listed(self.project(request, project_id, "name"))})

    def post(self, request, project_id):
        project = self.project(request, project_id, "name")
        payload = validated(FileAttachSerializer, request.data)
        row, created = files.attach(request, project, payload["file_id"], payload["kind"])
        return Response(files.as_json(row), status=status.HTTP_201_CREATED if created else status.HTTP_200_OK)


class ProjectFileDetailView(_StatsView):
    def patch(self, request, project_id, row_id):
        project = self.project(request, project_id, "name")
        payload = validated(FileSniffSerializer, request.data)
        return Response(files.as_json(files.set_sniff(project, row_id, payload["sniff"])))

    def delete(self, request, project_id, row_id):
        files.detach(self.project(request, project_id, "name"), row_id)
        return Response(status=status.HTTP_204_NO_CONTENT)


class ProjectFileContentView(_StatsView):
    def get(self, request, project_id, row_id):
        return files.content(self.project(request, project_id, "name"), row_id)


class ThreadListView(_StatsView):
    def get(self, request, project_id):
        project = self.project(request, project_id, "name")
        return Response({"threads": threads.recent(project, request.user)})

    def post(self, request, project_id):
        project = self.project(request, project_id, "name")
        payload = validated(ThreadCreateSerializer, request.data)
        thread = threads.create(project, request.user, payload["title"])
        return Response(threads.as_json(thread, with_state=True), status=status.HTTP_201_CREATED)


class _ThreadView(_StatsView):
    def thread(self, request, project_id, thread_id):
        project = self.project(request, project_id, "name")
        return get_object_or_404(StatsThread, id=thread_id, project=project, user=request.user)


class ThreadDetailView(_ThreadView):
    def get(self, request, project_id, thread_id):
        return Response(threads.as_json(self.thread(request, project_id, thread_id), with_state=True))

    def put(self, request, project_id, thread_id):
        thread = self.thread(request, project_id, thread_id)
        payload = validated(ThreadSaveSerializer, request.data)
        try:
            threads.save(thread, payload)
        except msgs.MissingMessages as e:
            return Response(
                {"message": "Some messages aren't saved yet. Send the whole conversation.", "missing": e.ids[:50]},
                status=status.HTTP_409_CONFLICT,
            )
        return Response(threads.as_json(thread))

    def delete(self, request, project_id, thread_id):
        threads.delete(self.thread(request, project_id, thread_id))
        return Response(status=status.HTTP_204_NO_CONTENT)


class ThreadMessagesView(_ThreadView):
    def get(self, request, project_id, thread_id):
        thread = self.thread(request, project_id, thread_id)
        query = validated(MessagePageQuerySerializer, request.query_params)
        offset, limit = query["offset"], query["limit"]
        rows = thread.messages.all()
        page = [msgs.as_ui(m) for m in rows[offset:offset + limit]]
        return Response(_paged("messages", page, rows.count(), offset))


MAX_PROBLEM_CHARS = 500


def _chat_error(message, code, detail=None):
    body = {"error": message}
    if detail:
        body["detail"] = detail[:MAX_PROBLEM_CHARS]
    return JsonResponse(body, status=code)


class ChatView(_StatsView):
    def post(self, request, project_id):
        self.project(request, project_id, "name")
        payload = ChatRequestSerializer(data=request.data)
        if not payload.is_valid():
            return _chat_error("invalid request", status.HTTP_400_BAD_REQUEST, "; ".join(problems(payload.errors)))
        cfg = chat.config()
        if cfg["provider"] == "openrouter" and not chat.configured():
            return _chat_error(chat.NOT_CONFIGURED, status.HTTP_500_INTERNAL_SERVER_ERROR)
        data = payload.validated_data
        try:
            params, active = chat.request_params(
                messages=data["messages"],
                digest=data.get("digest"),
                flags=data["flags"],
                text_only=data["textOnly"],
                after_stall=data["afterStall"],
                user_id=str(request.user.id),
                cfg=cfg,
            )
        except Exception as e:
            return _chat_error("invalid request", status.HTTP_400_BAD_REQUEST, str(e))
        response = StreamingHttpResponse(
            stream_reply(params=params, cfg=cfg, active=active), content_type="text/event-stream"
        )
        for name, value in HEADERS.items():
            response[name] = value
        return response


def _engine_user(request, project_id):
    auth = JWTAuthentication().authenticate(request)
    if auth is None:
        raise NotAuthenticated()
    projects.get(auth[0], project_id, "name")
    return auth[0]


def _engine_view(methods):
    def wrap(handler):
        @csrf_exempt
        @wraps(handler)
        async def view(request, project_id, **kwargs):
            if request.method not in methods:
                return JsonResponse({"message": "Method not allowed."}, status=405)
            try:
                user = await sync_to_async(_engine_user)(request, project_id)
                try:
                    body = json.loads(request.body or b"{}")
                except ValueError:
                    raise ParseError("Invalid JSON.")
                if not isinstance(body, dict):
                    raise ParseError("Invalid JSON.")
                return JsonResponse(await handler(request, user, project_id, body, **kwargs))
            except APIException as e:
                detail = e.detail if isinstance(e.detail, dict) else {"message": str(e.detail)}
                return JsonResponse(detail, status=e.status_code)
            except engine.EngineError as e:
                return JsonResponse({"message": str(e)}, status=e.status)
        return view
    return wrap


@_engine_view({"POST", "DELETE"})
async def engine_session(request, user, project_id, body):
    if request.method == "DELETE":
        await engine.end(project_id, user.id)
        return {"ok": True}
    payload = validated(EngineSessionSerializer, body)
    await engine.start(project_id, user.id, fresh=payload["fresh"])
    return {"ok": True}


@_engine_view({"POST"})
async def engine_file(request, user, project_id, body, row_id):
    payload = validated(EngineFileSerializer, body)
    return await engine.load_file(project_id, user.id, row_id, payload.get("path"))


@_engine_view({"POST"})
async def engine_call(request, user, project_id, body):
    payload = validated(EngineCallSerializer, body)
    return await engine.run(project_id, user.id, {"op": "call", "fn": payload["fn"], "args": payload["args"]})


@_engine_view({"POST"})
async def engine_run_code(request, user, project_id, body):
    payload = validated(EngineCodeSerializer, body)
    seconds = payload["timeout_ms"] / 1000 if "timeout_ms" in payload else None
    msg = {"op": "run_code", "code": payload["code"], "read_only": payload["read_only"]}
    return await engine.run(project_id, user.id, msg, seconds)


@_engine_view({"POST"})
async def engine_run_step(request, user, project_id, body):
    payload = validated(EngineStepSerializer, body)
    msg = {"op": "run_step", "code": payload["code"], "targets": payload["targets"]}
    return await engine.run(project_id, user.id, msg, settings.STATS_ENGINE_CALL_SECONDS)


@_engine_view({"POST"})
async def engine_snapshot(request, user, project_id, body):
    payload = validated(EngineSnapshotSerializer, body)
    return await engine.run(project_id, user.id, {"op": "snapshot", "ds": payload["ds"], "key": payload["key"]})


@_engine_view({"POST"})
async def engine_restore(request, user, project_id, body):
    payload = validated(EngineSnapshotSerializer, body)
    return await engine.run(project_id, user.id, {"op": "restore", "ds": payload["ds"], "key": payload["key"]})
