from rest_framework import serializers

from apps.projectassistant.serializers import (
    AnyText,
    ChatMessageSerializer,
    JSONBoolean,
    JSONInteger,
    JSONText,
    JSONObject,
    MessagePageQuerySerializer,
    ThreadCreateSerializer,
    ThreadSaveSerializer,
    validated,
)
from apps.projectassistant.chat.convert import well_formed

from .models import StatsProject, StatsProjectFile
from .services.chat import spec

__all__ = [
    "ChatRequestSerializer",
    "EngineCallSerializer",
    "EngineCodeSerializer",
    "EngineFileSerializer",
    "EngineSessionSerializer",
    "EngineSnapshotSerializer",
    "EngineStepSerializer",
    "FileAttachSerializer",
    "FileSniffSerializer",
    "MessagePageQuerySerializer",
    "ProjectCreateSerializer",
    "ProjectRenameSerializer",
    "StateSaveSerializer",
    "ThreadCreateSerializer",
    "ThreadSaveSerializer",
    "validated",
]

MAX_NAME = StatsProject._meta.get_field("name").max_length


def clean_name(value) -> str:
    return well_formed(value or "").replace("\x00", "").strip()[:MAX_NAME]


class ProjectCreateSerializer(serializers.Serializer):
    name = AnyText(max_length=MAX_NAME * 4)

    def validate_name(self, value):
        name = clean_name(value)
        if not name:
            raise serializers.ValidationError("Give the project a name.")
        return name


class ProjectRenameSerializer(ProjectCreateSerializer):
    pass


class StateSaveSerializer(serializers.Serializer):
    state = JSONObject()
    version = JSONInteger(min_value=0)


class FileAttachSerializer(serializers.Serializer):
    file_id = JSONInteger(min_value=1)
    kind = serializers.ChoiceField(choices=[k for k, _ in StatsProjectFile.KINDS])


class FileSniffSerializer(serializers.Serializer):
    sniff = JSONObject(allow_null=True)


ENGINE_CALLS = (
    "sniff_file", "peek_file", "import_dataset", "profile_dataset", "columns_info",
    "page", "values", "find_quotes", "drop", "reset_data",
)
MAX_CODE = 200_000
MAX_NAME_ARG = 500


class EngineSessionSerializer(serializers.Serializer):
    fresh = JSONBoolean(required=False, default=False)


class EngineFileSerializer(serializers.Serializer):
    path = JSONText(max_length=MAX_NAME_ARG, required=False)


class EngineCallSerializer(serializers.Serializer):
    fn = serializers.ChoiceField(choices=ENGINE_CALLS)
    args = serializers.ListField(required=False, default=list, max_length=8)


class EngineCodeSerializer(serializers.Serializer):
    code = AnyText(max_length=MAX_CODE)
    read_only = JSONBoolean(required=False, default=True)
    timeout_ms = JSONInteger(min_value=1000, required=False)


class EngineStepSerializer(serializers.Serializer):
    code = AnyText(max_length=MAX_CODE)
    targets = serializers.ListField(child=JSONText(max_length=MAX_NAME_ARG), max_length=50)


class EngineSnapshotSerializer(serializers.Serializer):
    ds = JSONText(max_length=MAX_NAME_ARG)
    key = JSONText(max_length=MAX_NAME_ARG)


CHAT_LIMITS = spec()["limits"]


class ChatFlagsSerializer(serializers.Serializer):
    hasFiles = JSONBoolean()
    hasUnimported = JSONBoolean()
    hasDocuments = JSONBoolean()
    datasets = JSONInteger(min_value=0)
    hasDictionary = JSONBoolean()
    hasOpenText = JSONBoolean()
    hasCodedThemes = JSONBoolean()
    artifacts = JSONInteger(min_value=0)
    importIssues = JSONBoolean(required=False)
    needsAutonomy = JSONBoolean(required=False)
    chartsToSubtitle = JSONInteger(min_value=0, required=False)


class ChatRequestSerializer(serializers.Serializer):
    messages = ChatMessageSerializer(many=True, max_length=CHAT_LIMITS["messages"])
    digest = AnyText(required=False, allow_null=True, allow_blank=True, max_length=CHAT_LIMITS["digest_chars"])
    flags = ChatFlagsSerializer()
    textOnly = JSONBoolean(default=False)
    afterStall = JSONBoolean(default=False)
    userId = JSONText(required=False, max_length=64)
