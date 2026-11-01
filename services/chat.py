import json
import os
from functools import lru_cache
from pathlib import Path

from apps.projectassistant.chat.config import provider_options
from apps.projectassistant.chat.convert import to_model_messages, well_formed, with_digest

SPEC_FILE = Path(__file__).resolve().parent.parent / "spec" / "stats_spec.json"
NOT_CONFIGURED = "AI_NOT_CONFIGURED: The AI service isn't set up on this server."
BASE_TOOLS = ("ask_user", "update_plan", "get_state", "run_python", "open_workspace", "suggest_next_steps")


@lru_cache(maxsize=1)
def spec() -> dict:
    return json.loads(SPEC_FILE.read_text(encoding="utf-8"))


def active_tool_names(flags: dict) -> list:
    names = list(BASE_TOOLS)
    datasets = flags.get("datasets") or 0
    if not flags.get("hasFiles"):
        names.append("import_social")
    if flags.get("hasFiles") and (flags.get("hasUnimported") or datasets == 0 or flags.get("importIssues")):
        names += ["peek_file", "import_table"]
    if flags.get("hasDocuments") or datasets > 0:
        names.append("update_brief")
    if datasets > 0:
        names += ["get_data", "set_variables", "propose_cleaning", "toggle_steps", "analyze", "make_chart", "scan_segments"]
    if datasets > 1:
        names.append("link_datasets")
    if flags.get("hasOpenText"):
        names.append("qual_code")
    if flags.get("hasCodedThemes"):
        names.append("qual_breakdown")
    if (flags.get("artifacts") or 0) > 0:
        names += ["draft_section", "export", "set_chart_colors"]
    if flags.get("chartsToSubtitle"):
        names.append("set_chart_subtitles")
    return names


def active_tools(flags: dict) -> dict:
    names = set(active_tool_names(flags))
    return {t["name"]: t for t in spec()["tools"] if t["name"] in names}


def _float_env(name: str, default: float) -> float:
    try:
        value = float(os.getenv(name, ""))
    except ValueError:
        return default
    return value if value > 0 else default


def _list_env(name: str, default: list) -> list:
    value = os.getenv(name)
    if not value:
        return list(default)
    if value.strip() == "none":
        return []
    return [s.strip() for s in value.split(",") if s.strip()]


def config() -> dict:
    d = spec()["defaults"]
    model = os.getenv("STATS_LLM_MODEL") or d["model"]
    reasoning = os.getenv("STATS_LLM_REASONING")
    if reasoning is None:
        reasoning = d["reasoning"] if model == d["model"] else None
    return {
        "provider": "mock" if os.getenv("STATS_LLM_PROVIDER") == "mock" else "openrouter",
        "model": model,
        "fallbacks": [m for m in _list_env("STATS_LLM_FALLBACK_MODELS", d["fallbacks"]) if m != model],
        "reasoning": reasoning if reasoning and reasoning != "default" else None,
        "data_policy": "deny" if os.getenv("STATS_LLM_DATA_POLICY") == "deny" else "allow",
        "temperature": _float_env("STATS_LLM_TEMPERATURE", d["temperature"]),
        "total_ms": _float_env("STATS_LLM_TOTAL_MS", d["total_ms"]),
        "first_chunk_ms": _float_env("STATS_LLM_FIRST_CHUNK_MS", d["first_chunk_ms"]),
        "chunk_ms": _float_env("STATS_LLM_CHUNK_MS", d["chunk_ms"]),
    }


def configured() -> bool:
    return bool(os.getenv("OPENROUTER_API_KEY") and os.getenv("OPENROUTER_BASE_URL"))


def _tool_choice(text_only: bool, force_ask: bool):
    if force_ask:
        return {"type": "function", "function": {"name": "ask_user"}}
    return "none" if text_only else "auto"


def request_params(*, messages, digest, flags, text_only, after_stall, user_id, cfg) -> tuple:
    prompts = spec()["prompts"]
    extra = prompts["words_only"] if text_only else prompts["after_stall"] if after_stall else None
    tools = active_tools(flags)
    last_is_user = bool(messages) and messages[-1].get("role") == "user"
    force_ask = not text_only and bool(flags.get("needsAutonomy")) and "ask_user" in tools and last_is_user
    params = {
        "model": cfg["model"],
        "messages": to_model_messages(spec()["system_prompt"], with_digest(messages, well_formed(digest)), extra),
        "tools": [{"type": "function", "function": t} for t in tools.values()],
        "tool_choice": _tool_choice(text_only, force_ask),
        "temperature": cfg["temperature"],
        "stream": True,
        "extra_body": provider_options(cfg),
    }
    if user_id:
        params["user"] = user_id
    return params, {name: t["parameters"] for name, t in tools.items()}
